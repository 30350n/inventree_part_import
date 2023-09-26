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

This file is used to configure authentification to your InvenTree host.
It has two parameters:

- `host`: the host url to connect to (including port, if required)
- `token`: the user token to authentificate with (this will be retrieved automatically by the CLI)

#### `categories.yaml`

TODO ...

#### `parameters.yaml`

TODO ...

## Goal

The goal of this project is to not exist anymore in it's current form. Ideally everything the
CLI tool does would be directly available from the InvenTree web interface. This will most
likely be done by implementing plugins which offer the required functionality for each supplier.

## Credits

- [InvenTree](https://inventree.org/) ([@SchrodingersGat](https://github.com/SchrodingersGat) and [@matmair](https://github.com/matmair))
  This project wouldn't exist without their brilliant work on creating the awesome open-source
  inventory managment solution.

- [Ki-nTree](https://github.com/sparkmicro/Ki-nTree) ([@eeintech](https://github.com/eeintech))
  This project is inspired by Ki-nTree and aims to fix most of the issues I've had with it.
  It only provides the part importing functionality, but tries to improve it in every way.

## License

- This project is licensed under [GPLv3](LICENSE).
