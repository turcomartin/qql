FROM postgres:16

# Copy init SQL, shell script, and data into the image
COPY init/ /docker-entrypoint-initdb.d/

# Ensure the shell script is executable inside the image
RUN chmod +x /docker-entrypoint-initdb.d/create_readonly_user.sh