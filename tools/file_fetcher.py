"""File scraper and validation tool for PlanetSide 2 API files.

This script supports multiple modes, including complete dumps, checking
ID range gaps, and incremental scraping via CI/CD.

Call this script with the --help option for more information.
"""

import argparse
import asyncio
import contextlib
import pathlib

import aiofiles
import aiohttp
import yarl
from PIL import Image

_ENDPOINT = yarl.URL('https://census.daybreakgames.com/')


async def dump(path: pathlib.Path, max_image_id: int, offset: int = 0,
               batch_size: int = 20) -> None:
    """Dump bulk files from the API.

    `max_image_id` specifies the upper bound of the image ID range to
    download. `offset` may be used to skip the first `offset` images.

    :param path: Output directory to write files to. Any existing files
        will be overwritten if their names collide with downloaded
        files.
    :type path: pathlib.Path
    :param max_image_id: Upper bound of image ID range to download.
    :type max_image_id: int
    :param offset: Lower bound of image ID range to download.
    :type offset: int, optional
    :param batch_size: Maximum number of concurrent downloads.
    :type batch_size: int, optional
    """
    if max_image_id <= 0:
        raise ValueError('max_image_id must be positive')
    if offset < 0:
        raise ValueError('offset must be non-negative')
    if offset >= max_image_id:
        raise ValueError('offset must be less than max_image_id')

    # Create output directory if it doesn't exist
    path.mkdir(parents=True, exist_ok=True)

    # Download files
    async with aiohttp.ClientSession(base_url=_ENDPOINT) as session:
        tasks: list[asyncio.Task[None]] = []
        for image_id in range(offset + 1, max_image_id + 1):
            tasks.append(asyncio.create_task(
                _download_and_verify_image(session, path, image_id)))
            if len(tasks) >= batch_size:
                await asyncio.gather(*tasks)
                tasks.clear()

        if tasks:
            await asyncio.gather(*tasks)
            tasks.clear()


async def gapfill(path: pathlib.Path, offset: int = 0,
                  batch_size: int = 20) -> None:
    """Check all missing IDs to see if they have been populated.

    This expects to be run over an existing dump directory, and will
    attempt to download any missing files. A file is considered to be
    missing if a higher ID exists in the directory.

    :param path: Target directory to scan for missing files. Newly
        downloaded files will also be placed in this directory.
    :type path: pathlib.Path
    :param offset: Starting offset for missing files.
    :type offset: int
    :param batch_size: Maximum number of concurrent downloads.
    :type batch_size: int, optional
    """
    if offset < 0:
        raise ValueError('offset must be non-negative')
    if not path.is_dir():
        raise ValueError('path must be a directory')

    # Find the highest ID in the directory
    max_image_id: int | None = None
    for file in path.iterdir():
        try:
            image_id = int(file.stem)
        except ValueError:
            continue
        if max_image_id is None or image_id > max_image_id:
            max_image_id = image_id

    if max_image_id is None:
        return

    # Download missing files
    async with aiohttp.ClientSession(base_url=_ENDPOINT) as session:
        tasks: list[asyncio.Task[None]] = []
        for image_id in range(offset, max_image_id):
            if not (path / f'{image_id}.png').exists():
                tasks.append(asyncio.create_task(
                    _download_image(session, path, image_id)))
                if len(tasks) >= batch_size:
                    await asyncio.gather(*tasks)
                    tasks.clear()
        if tasks:
            await asyncio.gather(*tasks)
            tasks.clear()


async def incremental(path: pathlib.Path, count: int = 1000,
                      batch_size: int = 20) -> None:
    """Scan for new files that may have been added since the last run.

    This will check up to `count` IDs past the last ID in the directory
    and attempt to download them. This in turn means that new assets
    following a gap of at least `count` IDs will never be detected.

    :param path: Target directory to download new files to.
    :type path: pathlib.Path
    :param count: Maximum number of images to download in a single run.
        If more than `count` assets are added at once, this means that
        it might take multiple runs to download them all.
    :type count: int
    :param batch_size: Maximum number of concurrent downloads.
    :type batch_size: int, optional
    """
    if count < 1:
        raise ValueError('count must be positive')
    if not path.is_dir():
        raise ValueError('path must be a directory')

    offset = _find_max_image_id(path) + 1
    print(f'Starting incremental dump at ID {offset}')
    await dump(path, offset + count, offset, batch_size)


async def _download_image(session: aiohttp.ClientSession, path: pathlib.Path,
                          image_id: int) -> None:
    """Download the given file from the PS2 API.

    The provided session must already be configured with the correct
    base URL.

    :param session: aiohttp session to use for the download.
    :type session: aiohttp.ClientSession
    :param path: Output directory to write files to. Any existing files
        will be overwritten.
    :type path: pathlib.Path
    :param image_id: ID of the image to download.
    :type image_id: int
    """
    filename = f'{image_id}.png'
    url = f'/files/ps2/images/static/{filename}'
    async with session.get(url) as response:
        id_str = f'{image_id:<6}'
        if response.status == 200:
            async with aiofiles.open(path / f'{image_id}.png', 'wb') as file:
                await file.write(await response.read())
            print(f'{id_str}: downloaded')
        elif response.status == 404:
            print(f'{id_str}: not found')
        else:
            print(f'{id_str}: skipped {response.status}')


async def _download_and_verify_image(session: aiohttp.ClientSession,
                                     path: pathlib.Path, image_id: int,
                                     attempts: int = 5) -> None:
    """Download and verify the given image file.

    This function will attempt to open the downloaded image file using
    PIL to ensure it is a valid PNG file. If the file is not valid, it
    will be deleted and a new download will be attempted.

    :param session: aiohttp session to use for the download.
    :type session: aiohttp.ClientSession
    :param path: Output directory to write files to. Any existing files
        will be overwritten.
    :type path: pathlib.Path
    :param image_id: ID of the image to download.
    :type image_id: int
    :param attempts: Number of attempts to download a working image.
    :type attempts: int, optional
    """
    filename = path / f'{image_id}.png'
    for _ in range(attempts):
        await _download_image(session, path, image_id)
        with contextlib.suppress(BaseException):
            with Image.open(filename) as img:
                img.verify()
            print(f'{image_id:<6}: verified')
            return
        print(f'{image_id:<6}: failed to verify, retrying...')
        filename.unlink(missing_ok=True)
    print(f'{image_id:<6}: failed to verify, deleting file')


def _find_max_image_id(path: pathlib.Path) -> int:
    """Find the highest ID stored in the output directory.

    :param path: The output directory to search.
    :type path: pathlib.Path
    :return: The highest ID found in the output directory.
    """
    max_image_id = 0
    for file_ in path.iterdir():
        if file_.suffix == '.png':
            try:
                max_image_id = max(max_image_id, int(file_.stem))
            except ValueError as err:
                raise ValueError(
                    f'Invalid file name: {file_.name}. Expected the output '
                    'directory to only contain names matching the "<id>.png" '
                    'pattern.') from err
    return max_image_id


async def main(args: argparse.Namespace) -> None:
    """Main entry point for the script.

    :param args: Parsed command-line arguments.
    :type args: argparse.Namespace
    """
    # Run in the appropriate mode
    if args.mode == 'dump':
        coro = dump(args.path, args.max_image_id, args.offset, args.batch_size)
    elif args.mode == 'gapfill':
        coro = gapfill(args.path, args.offset, args.batch_size)
    elif args.mode == 'incremental':
        coro = incremental(args.path, args.count, args.batch_size)
    else:
        raise RuntimeError(f'Unknown mode: {args.mode}')

    # Run the coroutine
    try:
        await coro
    except aiohttp.ClientError as err:
        print(f'Exited with error: {err}')

    # NOTE: The aiohttp session closing immediately before the program exits
    # can prevent some cleanup tasks from running. This is a simple workaround
    # that ensures all requests, connections, and other resources are cleaned
    # up and no warnings are printed.
    await asyncio.sleep(1.0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('PS2 API File Fetcher')

    # Common arguments
    parser.add_argument(
        'path', type=pathlib.Path, default='./api-files', nargs='?',
        help='target directory containing the downloaded API files')
    parser.add_argument(
        '--batch_size', '-b', type=int, default=20,
        help='maximum number of concurrent downloads')

    # Modes
    modes = parser.add_subparsers(title='Modes', dest='mode')
    modes.required = True

    # "Dump" mode = download all/many files
    dump_parser = modes.add_parser(
        'dump', help='download bulk API files')
    dump_parser.add_argument(
        'max_image_id', type=int, help='upper bound of image ID range')
    dump_parser.add_argument(
        '--offset', '-o', type=int, default=0, nargs='?',
        help='starting offset for the image ID range')

    # "Gapfill" mode = redownload missing files
    gapfill_parser = modes.add_parser(
        'gapfill', help='redownload missing files')
    gapfill_parser.add_argument(
        '--offset', '-o', type=int, default=0, nargs='?',
        help='minimum image ID to download')

    # "Incremental" mode = check for new files (CI/CD)
    parser_incremental = modes.add_parser(
        'incremental', help='check for new files')
    parser_incremental.add_argument(
        '--count', '-c', type=int, default=1000, nargs='?',
        help='maximum number of images to download in a single script run')

    asyncio.run(main(parser.parse_args()))
