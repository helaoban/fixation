import asyncio as aio
import contextlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
import logging
import uuid
import typing as t

import aioredis  # type: ignore

import pytest  # type: ignore
import fix
from fixtrate.message import FixMessage
from utils import aio as aioutils
from fixtrate.store.inmemory import reset_store_data


logger = logging.getLogger(__name__)


@dataclass
class MockFixServerConfig:
    host: str = "127.0.0.1"
    port: int = 8686
    clients: t.List[str] = field(default_factory=list)
    store: str = "inmemory://"


class MockFixServer:

    def __init__(
        self,
        config: t.Optional[MockFixServerConfig],
    ) -> None:
        self.config = config or MockFixServerConfig()
        self.sessions: t.List[fix.FixSession] = []

    async def stream_client_session(self, session):
        try:
            async for msg in session:
                pass
        except ConnectionAbortedError:
            pass
        except Exception as error:
            logger.exception(error)

    async def serve(self) -> None:
        tasks = []
        try:
            async with fix.bind(**asdict(self.config)) as server:
                async for session in server:
                    self.sessions.append(session)
                    coro = self.stream_client_session(session)
                    tasks.append(aio.create_task(coro))
        except aio.CancelledError:
            for task in tasks:
                await aioutils.cancel_suppress(task)
            raise


async def _clear_redis(url: str):
    redis = await aioredis.create_redis(url)
    keys = await redis.keys("seatrade-test*")
    if len(keys) > 0:
        await redis.delete(*keys)
    redis.close()
    await redis.wait_closed()


@pytest.fixture
def store_data():
    return dict()


@pytest.fixture(params=["inmemory", "redis"])
async def store_dsn(request):
    if request.param == "redis":
        redis_url = "redis://127.0.0.1:6379/"
        await _clear_redis(redis_url)
        yield redis_url + "?prefix=seatrade-test"
        await _clear_redis(redis_url)
    else:
        reset_store_data()
        yield "inmemory://"
        reset_store_data()


@pytest.fixture
def hb_int(request):
    return request.param if hasattr(request, "param") else 30


@pytest.fixture
def server_config(store_dsn, hb_int) -> MockFixServerConfig:
    clients = [f"fix://TESTCLIENT:TESTSERVER@127.0.0.1:8686/?hb_int={hb_int}"]
    return MockFixServerConfig(
        host="127.0.0.1",
        port=8686,
        clients=clients,
        store=store_dsn,
    )


@pytest.fixture
def client_dsn(request, hb_int) -> str:
    default = f"fix://TESTCLIENT:TESTSERVER@127.0.0.1:8686/?hb_int={hb_int}"
    rv = request.param if hasattr(request, "param") else default
    return rv


@pytest.fixture
async def test_server(
    request,
    server_config: MockFixServerConfig,
) -> t.AsyncIterator[MockFixServer]:
    server = MockFixServer(server_config)
    task = aio.create_task(server.serve())
    await aio.sleep(0.1)
    yield server
    task.cancel()
    with contextlib.suppress(aio.CancelledError):
        await task


@pytest.fixture
def order_request() -> FixMessage:
    order = FixMessage()
    order.append_pair(fix.FixTag.MsgType, fix.FixMsgType.NEW_ORDER_SINGLE)
    order.append_pair(fix.FixTag.ClOrdID, str(uuid.uuid4()))
    order.append_pair(fix.FixTag.OrdType, fix.OrdType.LIMIT)
    order.append_pair(fix.FixTag.Symbol, 'UGAZ')
    order.append_pair(fix.FixTag.Side, fix.Side.BUY)
    order.append_pair(fix.FixTag.OrderQty, 100)
    order.append_pair(fix.FixTag.Price, 25.0)
    order.append_utc_timestamp(fix.FixTag.TransactTime, datetime.utcnow())
    return order
