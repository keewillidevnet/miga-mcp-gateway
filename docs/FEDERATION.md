# Federating with External Agent Directories

MIGA is architecturally ready for federation with external AGNTCY Agent
Directories, enabling multi-vendor, multi-organization agent ecosystems.

## What Federation Enables

When federated, MIGA's Gateway can discover and route to MCP servers
registered in external directories — not just its own cluster. This means:

- A ServiceNow MCP server registered in a partner's directory becomes
  discoverable by MIGA's Gateway
- Your MIGA platform servers become discoverable by external agent
  orchestrators
- Cross-organization incident response workflows become possible

## Current State (v1)

Federation is **not enabled by default** in v1 for demo reliability.
MIGA runs a local-only AGNTCY Directory node. The `peers` array in the
directory configuration is empty but ready to populate.

## Enabling Federation

### 1. Configure Directory Peers

Add peer directory URLs to your AGNTCY Directory configuration:

```yaml
# agntcy-directory config
peers:
  - url: https://partner-directory.example.com:8500
    trust_level: verified
  - url: https://vendor-directory.example.com:8500
    trust_level: discovery_only
```

### 2. Trust Levels

- **verified**: Full bidirectional trust — discover and route to remote servers
- **discovery_only**: Can discover remote servers but requires explicit allow-listing
- **blocked**: Peer is known but not trusted

### 3. Identity Verification

When routing to a federated server, the Gateway verifies the remote server's
AGNTCY Identity Badge against the issuing directory's public key. This ensures
cryptographic proof that the remote server is who it claims to be.

### 4. Security Considerations

- All federated communication should use mTLS
- Rate limiting applies to federated queries
- Audit logs include federation source metadata
- Destructive operations from federated servers always require local approval
- Data classification tags in OASF records control what's shared externally

## v2: SLIM Federation

In v2, AGNTCY SLIM (Secure Low-latency Interactive Messaging) replaces
Redis pub/sub for inter-service messaging. SLIM supports federated
messaging channels with MLS (Messaging Layer Security) encryption,
enabling cross-organization event correlation and coordinated incident
response with quantum-safe encryption.
