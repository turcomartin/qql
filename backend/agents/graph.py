"""
LangGraph pipeline definition.

Graph structure:
  START → orchestrator → [route by intent]
    "data" → eda_consultant → [route by verdict]
      "proceed" | "partial" → analyst → sql_agent → [retry or done]
      "infeasible" | "question" → END
    "chat" → conversation_agent → END
"""

from langgraph.graph import END, START, StateGraph

from config import settings

from .analyst import analyst_node
from .consultant import eda_consultant_node
from .conversation_agent import conversation_agent_node
from .orchestrator import orchestrator_node
from .sql_agent import sql_agent_node
from .state import AgentState


def _route_intent(state: AgentState) -> str:
    return state["intent"] or "chat"


def _route_consultant(state: AgentState) -> str:
    verdict = state.get("consultant_verdict") or "proceed"
    # "question" and "infeasible" have already emitted done events — go to END
    if verdict in ("infeasible", "question"):
        return "done"
    return "proceed"  # "proceed" and "partial" both continue to analyst → sql_agent


def _should_retry_sql(state: AgentState) -> str:
    """
    Decide whether the SQL Agent should retry or stop.

    Now that events are emitted directly (not accumulated in state), we use
    explicit state flags to detect success and non-retryable conditions:
      - is_timeout=True  → done (sql_agent already emitted error+done)
      - last_error=None  → done (success — sql_agent emitted sql+table+done)
      - sql_attempts >= max → failed
      - otherwise → retry
    """
    if state.get("is_timeout"):
        return "done"
    # sql_attempts > 0 guards against the initial state where last_error is None
    if state["sql_attempts"] > 0 and state.get("last_error") is None:
        return "done"
    if state["sql_attempts"] >= settings.max_sql_retries:
        return "failed"
    return "retry"


async def _finalize_failed_sql(state: AgentState) -> dict:
    """
    Called when SQL Agent exhausted retries without success.
    Emits a terminal error + done event directly to the SSE stream.
    """
    from streaming import emit  # local import avoids circular deps at module load

    await emit(
        {
            "type": "error",
            "content": (
                f"Could not generate a valid SQL query after {settings.max_sql_retries} attempts. "
                "Try rephrasing your question or asking for something simpler."
            ),
        }
    )
    await emit({"type": "done"})
    return {}


# Build graph
_graph = StateGraph(AgentState)

_graph.add_node("orchestrator", orchestrator_node)
_graph.add_node("eda_consultant", eda_consultant_node)
_graph.add_node("analyst", analyst_node)
_graph.add_node("sql_agent", sql_agent_node)
_graph.add_node("conversation_agent", conversation_agent_node)
_graph.add_node("finalize_failed_sql", _finalize_failed_sql)

_graph.add_edge(START, "orchestrator")

_graph.add_conditional_edges(
    "orchestrator",
    _route_intent,
    {"data": "eda_consultant", "chat": "conversation_agent"},
)

_graph.add_conditional_edges(
    "eda_consultant",
    _route_consultant,
    {"proceed": "analyst", "done": END},  # analyst runs before sql_agent
)

_graph.add_edge("analyst", "sql_agent")  # analyst always feeds into sql_agent

_graph.add_conditional_edges(
    "sql_agent",
    _should_retry_sql,
    {"retry": "sql_agent", "done": END, "failed": "finalize_failed_sql"},
)

_graph.add_edge("finalize_failed_sql", END)
_graph.add_edge("conversation_agent", END)

compiled_graph = _graph.compile()
