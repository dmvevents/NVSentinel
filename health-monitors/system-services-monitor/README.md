# System Services Monitor

Health monitor for the systemd unit layer on NVIDIA GPU nodes: Fabric Manager service health with flap detection, and GPU service lifecycle. Per-GPU fabric probe state is owned by gpu-health-monitor (DCGM 4.5.2 health watches); journal-pattern detection is owned by syslog-health-monitor (per ADR-050).

Documentation has been moved to the repo-wide `docs/` tree per project convention:

- **Component overview, scope, architecture, check categories** --
  [`docs/system-services-monitor.md`](../../docs/system-services-monitor.md)
- **CLI flags, environment variables, deployment recipes** --
  [`docs/configuration/system-services-monitor.md`](../../docs/configuration/system-services-monitor.md)
- **Architectural decision (split from `gpu-health-monitor`)** --
  [`docs/designs/049-system-services-monitor-scope.md`](../../docs/designs/049-system-services-monitor-scope.md)
- **Pod-level orphan detection for gpu-operator DaemonSets** --
  [`docs/monitoring-critical-operators.md`](../../docs/monitoring-critical-operators.md) (owned by `kubernetes-object-monitor`)

## Build & Test

```sh
make -C health-monitors/system-services-monitor lint-test
make -C health-monitors/system-services-monitor docker-build
```
