# InvenTree Part Import

This project offers a command line interface to easily import parts from suppliers like
DigiKey, LCSC, Mouser, etc. into your InvenTree instance.

## Installation

```sh
pipx install git+https://github.com/30350n/inventree_part_import.git
```

*(`pip` should also work, but [`pipx`](https://github.com/pypa/pipx) is the new recommended way to install standalone applications)*

## Basic Usage

To import parts, simply use the `inventree_part_import` command, followed by the supplier or
manufacturer part numbers of the parts you want to import.

```console
$ inventree_part_import <part_number_1> <part_number_2> ...
```

You can also batch import multiple parts from tabular data files (`.csv`, `.xlsx`, etc.) like
so:

```console
$ inventree_part_import parts.csv
```

## Configuration

#### `inventree.yaml`

This file is used to configure authentication to your InvenTree host.
It has two parameters:

- `host`: the host url to connect to (including port, if required)
- `token`: the user token to authenticate with (this will be retrieved automatically by the CLI)

#### `config.yaml`

This file is used to configure general settings of the CLI tool, as well as default locales.
The following parameters have to be set:

- `currency`: the default currency to use when searching suppliers (ISO4217 code)
- `language`: the default language to use when searching suppliers (ISO639 code)
- `location`: the default location to use when searching suppliers (ISO3166 code)
- `scrape`: whether or not web page scraping is allowed (this can get you temporarily blocked)

#### `suppliers.yaml`

This file is used to configure supplier specific behavior.
The following parameters are always available:

- `currency`: overrides the currency for searching this supplier (see [`config.yaml`](#configyaml))
- `language`: overrides the language for searching this supplier (see [`config.yaml`](#configyaml))
- `location`: overrides the location for searching this supplier (see [`config.yaml`](#configyaml))

Additionally suppliers can have extra parameters for authentifcation to their respective APIs.
These can be set via the CLI like so: `inventree_part_import --configure <supplier>`.

#### `categories.yaml`

TODO ...

#### `parameters.yaml`

TODO ...

#### Pre Creation Hooks (`hooks.py`)

Pre creation hooks are functions that get run after part information has been parsed from a
supplier, but before the InvenTree part gets created. They basically let you modify a part,
before it gets imported. This can be very useful in some cases.

For example, here's one that assigns transistors into different categories, based on their type:

```py
def fix_transistor_categories(api_part):
    if "BJT" in api_part.category_path[-1] or "Bipolar (BJT)" in api_part.category_path:
        transistor_type = api_part.parameters.get("Transistor Type", "")
        if "NPN" in transistor_type:
            api_part.category_path.append("NPN")
        elif "PNP" in transistor_type:
            api_part.category_path.append("PNP")
```

You can define any number of them in a `hooks.py` file in your configuration directory.
They'll get called in the order they're defined in.

For more examples, checkout my [config repository](https://github.com/30350n/inventree_part_import_config).

## Goal

The end goal of this project is to not exist anymore in it's current form. Ideally everything
the CLI tool does would be directly available from the InvenTree web interface. This will most
likely be done by implementing plugins which offer the required functionality for each supplier.

## Credits

- [InvenTree](https://inventree.org/) ([@SchrodingersGat](https://github.com/SchrodingersGat) and [@matmair](https://github.com/matmair))
  This project wouldn't exist without their brilliant work on creating the awesome open-source
  inventory management solution.

- [Ki-nTree](https://github.com/sparkmicro/Ki-nTree) ([@eeintech](https://github.com/eeintech))
  This project is inspired by Ki-nTree and aims to fix most of the issues I've had with it.
  It only provides the part importing functionality, but tries to improve it in every way.

## License

- This project is licensed under [GPLv3](LICENSE).
