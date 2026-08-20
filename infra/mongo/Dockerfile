FROM --platform=linux/amd64 mongo:8.0

COPY bootstrap-entrypoint.sh /usr/local/bin/bootstrap-entrypoint.sh
RUN chmod 755 /usr/local/bin/bootstrap-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/bootstrap-entrypoint.sh"]

