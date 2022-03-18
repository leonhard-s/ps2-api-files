"""Scraper for the PlanetSide 2 file endpoint."""

import argparse
import asyncio
import os
import pathlib
from typing import Any, Awaitable, List

import aiohttp
import aiofiles

# URL of the file endpoint
ENDPOINT = 'https://census.daybreakgames.com/files/ps2/images/static/'
# Output directory for the retrieved files
_output_dir = pathlib.Path('images/')


def find_last_id(dir_: pathlib.Path) -> int:
    """Find the last ID available in the output directory."""
    last_id = 0
    for file_ in dir_.iterdir():
        if file_.suffix == '.png':
            last_id = max(last_id, int(file_.stem))
    return last_id


async def fetch(id_: int,  output: pathlib.Path) -> None:
    print(f'Fetching {id_}')
    async with aiohttp.ClientSession() as session:
        url = f'{ENDPOINT}/{id_}.png'
        async with session.get(url) as response:
            if response.status == 200:
                file_ = await aiofiles.open(f'{output}/{id_}.png', mode='wb')
                await file_.write(await response.read())
                await file_.close()


async def main(dir_: str, offset: int, count: int, batch_size: int) -> None:
    """Async component of the "if __name__ == '__main__'" clause."""
    output_dir = pathlib.Path(dir_)
    # Create output directory if it does not exist yet
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
    # Task list, used to store a batch of requests
    tasks: List[Awaitable[Any]] = []
    # Main loop
    for id_ in range(offset, offset + count):
        tasks.append(fetch(id_, output_dir))
        # Flush task list if it is full
        if len(tasks) >= batch_size:
            await asyncio.gather(*tasks)
            tasks.clear()
    # Finish remaining tasks
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', '-d', type=str, default=_output_dir,
                        help='Output directory for the retrieved files')
    parser.add_argument('--offset', '-o', type=int, default=0,
                        help='Starting offset for image scraping')
    parser.add_argument('--auto-offset', '-a', action='store_true',
                        help='Automatically find the last ID available and '
                        'use it as the offset')
    parser.add_argument('--max_range', '-m', type=int, default=10_000,
                        help='Number of assets to retrieve')
    parser.add_argument('--batch_size', '-b', type=int, default=16,
                        help='Number of assets to fetch in parallel')
    args = parser.parse_args()
    loop = asyncio.new_event_loop()
    asset_offset = args.offset
    if args.auto_offset:
        asset_offset = find_last_id(args.directory) + 1
    loop.run_until_complete(
        main(args.directory, asset_offset, args.max_range, args.batch_size))
