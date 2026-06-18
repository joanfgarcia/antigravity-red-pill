"""
Antigravity IDE backends — Antigravity-specific bridge implementations.

	- agy_bridge.AgyBridge  (execution): agy CLI for Neon-Link commands + AWAKENINGs
	- grpc_bridge.GrpcBridge (extraction): gRPC-Web for the Chronicle pipeline

The GENERIC agent-bridge abstraction + factory now live in
``red_pill.swarm.bridges`` (AgentBridge, BackendType, create_bridge, …). These
implementations import the ABC from there. Imported lazily by the factory — not
eagerly here, to avoid pulling gRPC deps on every package import.

Config: IDE_BACKEND=agy|grpc|claude|local|auto in .env
"""
