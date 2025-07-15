"""Advanced synchronization tool for PS2 API image assets.

This script synchronizes image files from the CDN while also inspecting
their metadata from the Census REST API.

Depending on whether an image exists on the CDN and whether its metadata
is available, one of three naming conventions is used:

- `<image_id>.<description>.<type_id>.png`: Image and metadata found
- `<image_id>.unknown.0.png`: Image found, but no metadata on Census
- `<image_id>.<description>.<type_id>.notfound`: Metadata found, but
    image missing from CDN

This script is highly asynchronous and designed for performance and low
API load. REST requests are batched to minimize the number of individual
connections, while image downloads are handled concurrently and in
parallel to reduce the overall processing time.
"""

import argparse
import asyncio
import contextlib
import pathlib
import typing
from collections.abc import Awaitable

import aiofiles
import aiohttp
import auraxium
from auraxium import census
from auraxium.endpoints import DBG_FILES
from PIL import Image


class ImageMetadata(typing.TypedDict):
    """Metadata for an image from the Census REST API.

    This roughly corresponds to the JSON payload returned by the
    `ps2/image_set` endpoint on Census.
    """

    image_id: int
    description: str
    type_id: int


async def fetch_descriptions(client: auraxium.Client,
                             image_ids: list[int]) -> dict[int, ImageMetadata]:
    """Fetch descriptions for a list of image IDs from the REST API.

    Returns a mapping from image_id to ImageMetadata dicts. Note that
    not all image IDs may have metadata, so the returned dict's keys
    will not necessarily match the input list.
    """
    query = census.Query('image_set', namespace='ps2:v2',
                             service_id=client.service_id)
    query.limit(len(image_ids))
    query.add_term('image_id', ','.join(map(str, image_ids)))
    query.show('image_id', 'description', 'type_id')
    results: typing.Any = (await client.request(query))['image_set_list']
    descriptions: dict[int, ImageMetadata] = {}
    for element in typing.cast(list[dict[str, str]], results):
        image_id = int(element['image_id'])
        descriptions[image_id] = ImageMetadata(
            image_id=image_id,
            description=str(element['description']),
            type_id=int(element['type_id'])
        )
    # DEBUG: Show all images that had no metadata
    missing_ids = set(image_ids) - set(descriptions.keys())
    if missing_ids:
        print(f"Warning: No metadata found for image IDs: {missing_ids}")
    return descriptions


async def try_download_image(session: aiohttp.ClientSession, image_id: int,
                             asset_dir: pathlib.Path) -> bool:
    """Attempt to download an image from the CDN.

    Returns True if the image was successfully downloaded, False if not.
    """
    id_str = f'{image_id:<6}'
    url = DBG_FILES / f'{image_id}.png'
    file_path = asset_dir / f'{image_id}.png'
    with contextlib.suppress(BaseException):
        async with session.get(url) as response:
            if response.status == 200:
                async with aiofiles.open(file_path, 'wb') as file:
                    await file.write(await response.read())
                print(f'{id_str}: downloaded')
            elif response.status == 404:
                print(f'{id_str}: not found')
            else:
                print(f'{id_str}: skipped {response.status}')
            with Image.open(file_path) as img:
                img.verify()
                print(f'{id_str}: verified')
                return True
    print(f'{id_str}: failed to verify, deleting file')
    file_path.unlink(missing_ok=True)
    return False


async def fetch_and_verify_from_cdn(
        session: aiohttp.ClientSession, asset_dir: pathlib.Path,
        image_ids: list[int]) -> dict[int, bool]:
    """Fetch images from the CDN and verify them.

    Returns a mapping from image_id to a boolean indicating whether the
    image was successfully downloaded and verified.
    """
    results: dict[int, bool] = {}
    tasks: list[Awaitable[bool]] = []
    for image_id in image_ids:
        tasks.append(try_download_image(session, image_id, asset_dir))
    results_list = await asyncio.gather(*tasks)
    for image_id, success in zip(image_ids, results_list):
        results[image_id] = success
    return results


def _assemble_filename(image_id: int, image_found: bool,
                       desc: ImageMetadata | None) -> str | None:
    """Assemble the filename based on image existence and metadata."""
    if image_found and desc:
        return f'{image_id}.{desc["description"]}.{desc["type_id"]}.png'
    if image_found:
        return f'{image_id}.unknown.0.png'
    if desc:
        return f'{image_id}.{desc["description"]}.{desc["type_id"]}.notfound'
    return None




async def process_batch(image_ids: list[int], client: auraxium.Client,
                        asset_dir: pathlib.Path) -> None:
    """Process a batch of images and download their metadata."""
    descriptions = await fetch_descriptions(client, image_ids)
    async with aiohttp.ClientSession() as session:
        cdn_results = await fetch_and_verify_from_cdn(session, asset_dir,
                                                      image_ids)
    for image_id in image_ids:
        desc = descriptions.get(image_id)
        image_found = cdn_results.get(image_id, False)
        filename = _assemble_filename(image_id, image_found, desc)

        # Figure out if we need to create a new file
        if filename is None:
            print(f'Skipping image {image_id}: no valid filename could be '
                  'assembled')
            continue

        new_path = asset_dir / filename
        new_path.unlink(missing_ok=True)
        if image_found:
            old_path = asset_dir / f'{image_id}.png'
            if old_path.exists():
                print(f'Renaming {old_path} to {new_path}')
                old_path.rename(new_path)
            else:
                print(f'Image {image_id} found but no original file to rename')
        else:
            print(f'Image {image_id} not found on CDN, creating placeholder')
            # Create a placeholder file if the image was not found
            if desc:
                new_path.touch()
            else:
                print(f'No file and no metadata for image {image_id}, '
                      'skipping placeholder creation')


async def main(args: argparse.Namespace) -> None:
    """Main entry point for the advanced sync script."""
    asset_dir = args.asset_dir
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_ids = list(range(args.min_id, args.max_id + 1))
    batch_size = args.batch_size
    async with auraxium.Client(service_id=args.service_id) as client:
        batch_number = 0
        for i in range(0, len(image_ids), batch_size):
            batch_number += 1
            batch = image_ids[i:i+batch_size]
            print(f'Processing batch {batch_number} '
                  f'(start={batch[0]}, end={batch[-1]})')
            tasks: list[Awaitable[None]] = [
                process_batch(batch, client, asset_dir),
                asyncio.sleep(10.0),  # Limit polling rate
            ]
            await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser('PS2 Advanced Asset Sync')
    parser.add_argument(
        '--asset_dir', type=pathlib.Path, default=pathlib.Path('./synced-assets'),
        help='Target directory for synchronized assets')
    parser.add_argument(
        '--min_id', type=int, required=True,
        help='Minimum image ID (inclusive) to process')
    parser.add_argument(
        '--max_id', type=int, required=True,
        help='Maximum image ID (inclusive) to process')
    parser.add_argument(
        '--service_id', type=str, required=True,
        help='Service ID for Census API (for CI/CD use)')
    parser.add_argument(
        '--batch_size', type=int, default=50,
        help='Number of images to process per batch (default: 50)')
    _args = parser.parse_args()
    asyncio.run(main(_args))
