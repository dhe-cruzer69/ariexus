# ARIEX Control Contract

## Role
Secure agent runtime and orchestration layer.

## Observed baseline
- Typed task graphs
- Sandboxed filesystem
- Allow-listed terminal
- Approval workflow
- Immutable audit logging
- Retry, timeout and compensation planning

## Advanced upgrade track
1. Replace keyword intent parsing with structured LLM output plus schema validation.
2. Add policy-as-code for tool permissions.
3. Add signed/auditable execution receipts.
4. Add HTTP/browser tools behind explicit allowlists and approvals.
5. Add adversarial security tests for sandbox escapes and prompt/tool injection.
6. Add runtime telemetry to the fleet dashboard.

## Definition of done
No privileged tool executes without policy evaluation, audit evidence and the required approval state.
