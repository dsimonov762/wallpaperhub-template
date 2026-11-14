# Wallpaper Hub gateway: Envoy with the config baked in.
# Pinned: check https://hub.docker.com/r/envoyproxy/envoy/tags for a newer patch release.
FROM envoyproxy/envoy:v1.39.1

COPY envoy.yaml /etc/envoy/envoy.yaml

# 8080 public API, 8081 management (/health/*, /metrics). The admin interface stays on 127.0.0.1:9901.
EXPOSE 8080 8081

# The base image's default command is: envoy -c /etc/envoy/envoy.yaml
# Repeated here to add --concurrency 2: by default Envoy starts one worker thread per CPU thread the container
# sees (8 with processors=8 in .wslconfig) and every worker adds its own buffers and connection pools. Two are
# plenty for a local gateway. Raise it (or remove the flag) for load tests.
CMD ["envoy", "-c", "/etc/envoy/envoy.yaml", "--concurrency", "2"]
