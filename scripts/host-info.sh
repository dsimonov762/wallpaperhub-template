#!/usr/bin/env bash
# Prints what to do after `make host SVC=<name>`.   scripts/host-info.sh <svc>
svc="${1:?service}"; f="infra/host/$svc.env"
get() { sed -n "s/^$1=//p" "$f" | head -1; }
http="$(get HTTP_PORT)"; mgmt="$(get MGMT_PORT)"; grpc="$(get GRPC_PORT)"
cat <<TXT

$svc now runs on your machine. Its container is stopped; the network name '$svc' leads to a forwarder that passes
  $svc:8080 -> host port $http (API)   $svc:8081 -> $mgmt (management)${grpc:+   $svc:9090 -> $grpc (gRPC)}
to the process you start in the IDE. The gateway and the other services need no change.

Start it with the environment of  infra/host/$svc.env  and these three variables set (the file has them):
  HTTP_PORT=$http  MGMT_PORT=$mgmt${grpc:+  GRPC_PORT=$grpc}
The process must listen on all interfaces (0.0.0.0), not only on 127.0.0.1: the forwarder is a container and
reaches it through host.docker.internal. Windows asks once whether to allow it through the firewall: allow "Private".

Check it:   curl http://localhost:$mgmt/health/ready
Test it:    make conformance SVC=$svc ARGS="--api http://localhost:$http --mgmt http://localhost:$mgmt --log-file service.log --no-telemetry"
            (service.log: start the service with  2>&1 | tee service.log  or leave --log-file out to skip L1-L3)
Back:       make unhost SVC=$svc
TXT
