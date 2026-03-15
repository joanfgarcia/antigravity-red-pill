# Swarm Integration Guide

## 🛠️ Implementing a New Transport
To add a new database or communication channel, inherit from `SwarmTransport`:

```python
from red_pill.swarm.transport import SwarmTransport

class MyCustomTransport(SwarmTransport):
    def broadcast_identity(self, agent_id, metadata):
        # Implementation...
    def send_package(self, target_id, package):
        # Implementation...
```

Register it in `TransportManager` or add its configuration to `~/.agent/config/swarm_communities.json`.

## 🔑 Key Management
All keys are stored in `~/.agent/keys/`.
- `swarm_v2.priv`: Private X25519 key (chmod 600).
- `swarm_v2.pub`: Public X25519 key (Shared via Registry).

## 🛰️ Polling Integration
Integrate `SwarmMessagingSkill.poll_and_process()` into your application's main loop or a background worker (e.g., `LazarusPulse`).
