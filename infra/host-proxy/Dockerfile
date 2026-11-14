# TCP forwarder for "host mode": makes a service that runs on the developer's machine look like the container
# (account:8080, account:8081, account:9090 inside the compose network). Used by make host.
FROM alpine:3.24.4
RUN apk add --no-cache socat
COPY forward.sh /forward.sh
USER nobody
ENTRYPOINT ["/bin/sh", "/forward.sh"]
