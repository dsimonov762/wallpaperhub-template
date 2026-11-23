#!/usr/bin/env bash
# Static checks of the Helm chart, no cluster needed:  helm lint --strict, helm template, and kubeconform on what comes out, for
# every values file (deploy/helm/values/*/*.yaml) and every case in deploy/helm/service/ci/.   docs/KUBERNETES.md
#
#   scripts/k8s-lint.sh               helm and kubeconform are required (CI, make k8s-lint)
#   scripts/k8s-lint.sh --if-possible skip with a note when one of them is missing (the pre-commit hook)
set -u
cd "$(dirname "$0")/.." || exit 1
CHART=deploy/helm/service
# The Kubernetes version of the schemas: the one that kind v0.33.0 runs (raise it with kind, see deploy/kind/).
K8S_VERSION="${K8S_VERSION:-1.37.0}"

missing=()
command -v helm >/dev/null 2>&1 || missing+=(helm)
command -v kubeconform >/dev/null 2>&1 || missing+=(kubeconform)
if [ "${#missing[@]}" -gt 0 ]; then
  if [ "${1:-}" = "--if-possible" ]; then echo "k8s-lint: skipped, ${missing[*]} not installed (CI runs it; helm: https://helm.sh/docs/intro/install/, kubeconform: scripts/ci/install-kubeconform.sh ~/.local/bin)"; exit 0; fi
  echo "k8s-lint: ${missing[*]} not installed. helm: https://helm.sh/docs/intro/install/   kubeconform: scripts/ci/install-kubeconform.sh ~/.local/bin" >&2; exit 1
fi

fail=0; n=0
for f in deploy/helm/values/*/*.yaml "$CHART"/ci/*.yaml; do
  n=$((n+1))
  out="$(helm lint "$CHART" --strict -f "$f" 2>&1)" || { echo "FAIL helm lint -f $f"; echo "$out" | sed 's/^/     /'; fail=1; continue; }
  # --api-versions is not needed: the chart uses only the core groups, policy/v1, autoscaling/v2 and networking.k8s.io/v1
  rendered="$(helm template rel "$CHART" -f "$f" --namespace wallpaperhub 2>&1)" || { echo "FAIL helm template -f $f"; echo "$rendered" | sed 's/^/     /'; fail=1; continue; }
  if res="$(printf '%s\n' "$rendered" | kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" - 2>&1)"; then
    echo "  ok  $f  ($(printf '%s\n' "$res" | tail -1 | sed -E 's/.*Valid: ([0-9]+),.*/\1 resources valid/'))"
  else echo "FAIL kubeconform -f $f"; echo "$res" | sed 's/^/     /'; fail=1; fi
done

# The schema must refuse what it is meant to refuse (a typo in a values file is an error, not a silently ignored key).
if helm template rel "$CHART" -f deploy/helm/values/apps/account.yaml --set replicas=2 >/dev/null 2>&1; then
  echo "FAIL values.schema.json accepted an unknown key (--set replicas=2)"; fail=1
else echo "  ok  values.schema.json refuses an unknown key"; fi

[ "$fail" -eq 0 ] && echo "k8s-lint: $n values files pass helm lint --strict, helm template and kubeconform (Kubernetes $K8S_VERSION)"
exit "$fail"
