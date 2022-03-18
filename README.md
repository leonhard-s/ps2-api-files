# PlanetSide 2 API Files

This repository contains all files available through the PlanetSide 2 API's [file endpoint](https://census.daybreakgames.com/#url-pattern).

Note that this includes many icons that are not listed in the corresponding `image` or `image_set` collections, which is why this repository cannot provide friendly file names or any form of filtering by asset type (decals, camos, banners, etc.).

*This repository is automatically updated once a day.*

## Scraping Strategy

Once a day, the file scraper in this repository looks at the highest image ID it knows and proceeds to check the next 10'000 image IDs. If any new files are found, they are then added to the repository.

### Limitations

This scraping strategy attempts to strike a balance of being reasonably up-to-date and not loading the API file endpoint too heavily. In return, there are a number of noteworthy limitations and caveats:

- The scraper only "looks forward", and will not query a given asset ID once a higher ID has been found.
- It cannot detect existing IDs being updated with new assets, or gaps in the ID sequence being filled later.
- If new assets are added that are more than 10'000 IDs away from the highest ID found, the scraper will not bother checking it, resulting in it missing out on these new files.

If you come across any of these limitations or know of additional ID ranges that are not currently being checked, please [create an issue](https://github.com/leonhard-s/ps2-api-files/issues) so the scraping strategy can be adjusted.

## Performance Notes

This repository is quite large (>230 MB) and contains a large number of binary files (>25'000 at the time of writing).

This can cause performance issues with some Git integrations, use the regular command line tool if you encounter freezes or lags in your normal Git client.

Additionally, it is recommended to perform a shallow clone of this repository:

    git clone -–depth 1 https://github.com/leonhard-s/ps2-api-files

This will only grab the latest version of all files with minimal repository history, which is generally faster than performing a full clone.
