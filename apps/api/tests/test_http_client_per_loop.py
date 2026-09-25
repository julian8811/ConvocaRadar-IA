import asyncio

from app.core import http_client as hc


def test_closing_per_loop_client_releases_secondary_clients():
    main_loop = asyncio.new_event_loop()
    try:
        main_loop.run_until_complete(hc.http_client())

        async def _use_client():
            client = await hc.http_client()
            return client

        for _ in range(3):
            client = asyncio.run(hc.closing_per_loop_client(_use_client()))
            assert client.is_closed

        assert hc._secondary_clients == {}
    finally:
        main_loop.run_until_complete(hc.close_async_client())
        main_loop.close()
