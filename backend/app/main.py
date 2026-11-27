from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from abm_simulation.agents import BorrowerBase, HonestBorrower, Lender, StrategicDefaulter
from abm_simulation.models import MicroLendingBase, MicroLendingV1, MicroLendingV2, MicroLendingV3


MODEL_TYPES = {"V1": MicroLendingV1, "V2": MicroLendingV2, "V3": MicroLendingV3}


class SimulationConfig(BaseModel):
    version: str = Field(default="V3", pattern="^V[123]$")
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


class StepConfig(BaseModel):
    steps: int = Field(default=1, ge=1, le=60)


@dataclass
class SimulationService:
    model: MicroLendingBase = field(default_factory=MicroLendingV3)
    running: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None

    def reset(self, config: SimulationConfig) -> None:
        self.model = MODEL_TYPES[config.version](seed=config.seed)
        self.running = False

    def _agent_payload(self, agent: Any) -> dict[str, Any]:
        if isinstance(agent, Lender):
            agent_type = "lender"
            state = "ACTIVE" if agent.deposited > 0 else "IDLE"
            balance = agent.capital
            loan = 0.0
            credit_score = None
        elif isinstance(agent, StrategicDefaulter):
            agent_type = "strategic_defaulter"
            state = "DEFAULTED" if agent.is_defaulted else ("BORROWING" if agent.remaining_principal else "IDLE")
            balance = agent.income
            loan = agent.remaining_principal
            credit_score = agent.credit_score
        elif isinstance(agent, HonestBorrower):
            agent_type = "honest_borrower"
            state = "DEFAULTED" if agent.is_defaulted else ("REPAYING" if agent.remaining_principal else "IDLE")
            balance = agent.income
            loan = agent.remaining_principal
            credit_score = agent.credit_score
        else:
            return {}
        return {
            "id": str(agent.unique_id),
            "type": agent_type,
            "state": state,
            "balance": round(balance, 4),
            "income": round(getattr(agent, "income", 0.0), 4),
            "living_cost": round(getattr(agent, "living_cost", 0.0), 4),
            "loan_amount": round(loan, 4),
            "collateral": round(getattr(agent, "collateral", 0.0), 4),
            "guarantor_stake": round(getattr(agent, "guarantor_stake", 0.0), 4),
            "credit_score": credit_score,
            "is_defaulted": getattr(agent, "is_defaulted", False),
        }

    def snapshot(self) -> dict[str, Any]:
        agents = [self._agent_payload(agent) for agent in self.model.agents]
        agents = [agent for agent in agents if agent]
        borrowers = [agent for agent in agents if agent["type"] != "lender"]
        return {
            "month": self.model.month,
            "version": self.model.version,
            "seed": getattr(self.model, "seed", None),
            "running": self.running,
            "macro_shock": 30 <= self.model.month <= 35,
            "metrics": {
                "tvl": round(self.model.pool_cash + self.model.pool_borrowed + self.model.locked_collateral, 4),
                "available_liquidity": round(self.model.pool_cash, 4),
                "locked_collateral": round(self.model.locked_collateral, 4),
                "outstanding_debt": round(self.model.pool_borrowed, 4),
                "protocol_reserve": round(self.model.reserve, 4),
                "utilization": round(self.model.utilization, 6),
                "npl": round(self.model.npl_rate, 6),
                "borrow_apr": round(self.model.borrow_apr_avg, 6),
                "supply_apr": round(self.model.supply_rate, 6),
                "default_count": self.model.npl_events,
                "total_loans": self.model.completed_loans + self.model.npl_events + sum(
                    1 for agent in borrowers if agent["loan_amount"] > 0
                ),
                "active_borrowers": sum(1 for agent in borrowers if agent["loan_amount"] > 0),
                "active_lenders": sum(1 for agent in agents if agent["type"] == "lender" and agent["balance"] > 0),
            },
            "agents": agents,
            "connections": [],
            "events": [],
        }

    async def step(self, count: int = 1) -> dict[str, Any]:
        async with self.lock:
            for _ in range(count):
                if self.model.month >= 60:
                    self.running = False
                    break
                self.model.step()
            return self.snapshot()

    async def run(self) -> None:
        while self.running and self.model.month < 60:
            await self.step()
            await broadcast()
            await asyncio.sleep(0.15)
        self.running = False


service = SimulationService()
subscribers: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if service.task:
        service.task.cancel()


app = FastAPI(title="Vietnam P2P Micro-Lending API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast() -> None:
    payload = service.snapshot()
    disconnected = []
    for socket in subscribers:
        try:
            await socket.send_json(payload)
        except Exception:
            disconnected.append(socket)
    for socket in disconnected:
        subscribers.discard(socket)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/simulation/status")
async def status() -> dict[str, Any]:
    return service.snapshot()


@app.post("/api/simulation/config")
async def configure(config: SimulationConfig) -> dict[str, Any]:
    service.reset(config)
    await broadcast()
    return service.snapshot()


@app.post("/api/simulation/start")
async def start() -> dict[str, Any]:
    if not service.running:
        service.running = True
        service.task = asyncio.create_task(service.run())
    return service.snapshot()


@app.post("/api/simulation/pause")
async def pause() -> dict[str, Any]:
    service.running = False
    return service.snapshot()


@app.post("/api/simulation/resume")
async def resume() -> dict[str, Any]:
    return await start()


@app.post("/api/simulation/step")
async def step(config: StepConfig | None = None) -> dict[str, Any]:
    payload = await service.step(config.steps if config else 1)
    await broadcast()
    return payload


@app.post("/api/simulation/reset")
async def reset(config: SimulationConfig | None = None) -> dict[str, Any]:
    service.reset(config or SimulationConfig())
    await broadcast()
    return service.snapshot()


@app.get("/api/simulation/metrics")
async def metrics() -> dict[str, Any]:
    return service.snapshot()["metrics"]


@app.get("/api/simulation/agents")
async def agents() -> list[dict[str, Any]]:
    return service.snapshot()["agents"]


@app.get("/api/simulation/agents/{agent_id}")
async def agent(agent_id: str) -> dict[str, Any]:
    result = next((item for item in service.snapshot()["agents"] if item["id"] == agent_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return result


@app.get("/api/protocol/pool")
async def pool() -> dict[str, Any]:
    return service.snapshot()["metrics"]


@app.get("/api/protocol/interest-rate")
async def interest_rate() -> dict[str, float]:
    return {
        "borrow_apr": service.model.borrow_apr_avg,
        "supply_apr": service.model.supply_rate,
        "utilization": service.model.utilization,
    }


@app.get("/api/protocol/versions")
async def versions() -> list[dict[str, str]]:
    return [
        {"version": "V1", "description": "Fixed rate, no collateral"},
        {"version": "V2", "description": "Kinked rate and dynamic collateral"},
        {"version": "V3", "description": "V2 plus social guarantee stake"},
    ]


@app.get("/api/history")
async def history() -> list[dict[str, Any]]:
    rows = service.model.datacollector.get_model_vars_dataframe().reset_index()
    return rows.to_dict(orient="records")


@app.websocket("/ws/simulation")
async def simulation_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    subscribers.add(websocket)
    await websocket.send_json(service.snapshot())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        subscribers.discard(websocket)
