from dataclasses import dataclass, field

from inventree.part import ParameterTemplate, PartCategory, PartCategoryParameterTemplate

from .config import (CATEGORIES_CONFIG, PARAMETERS_CONFIG, get_categories_config,
                     get_parameters_config, update_config_file)
from .error_helper import *

def setup_categories_and_parameters(inventree_api):
    categories_config = get_categories_config(inventree_api)
    parameters_config = get_parameters_config(inventree_api)

    info("setting up categories ...")
    categories = parse_category_recursive(categories_config)
    parameters = parse_parameters(parameters_config)

    used_parameters = set.union(set(), *(set(c.parameters) for c in categories.values()))

    for name in parameters:
        if name not in used_parameters:
            warning(f"parameter '{name}' is defined in {CATEGORIES_CONFIG} but not being used")
    for name in used_parameters:
        if name not in parameters:
            warning(f"parameter '{name}' not defined in {PARAMETERS_CONFIG}")
            parameters[name] = Parameter(name, name, [], "")

    part_categories = {
        tuple(part_category.pathstring.split("/")): part_category
        for part_category in PartCategory.list(inventree_api)
    }

    for category in categories.values():
        part_category = part_categories.get(tuple(category.path))
        if part_category is None:
            info(f"creating category '{'/'.join(category.path)}' ...")
            parent = part_categories.get(tuple(category.path[:-1]))
            part_category = PartCategory.create(inventree_api, {
                "name": category.name,
                "description": category.description,
                "structural": category.structural,
                "parent": parent.pk if parent else None,
            })
            part_categories[tuple(category.path)] = part_category
            if getattr(inventree_api, "DRY_RUN", False):
                part_category.pathstring = "/".join(category.path)

        elif category.description != part_category.description:
            info(f"updating description for category '{'/'.join(category.path)}' ...")
            part_category.save({"description": category.description})

        path_str = part_category.pathstring
        if category.structural and not part_category.structural:
            warning(f"category '{path_str}' on host is not structural, but it should be")
        elif not category.structural and part_category.structural:
            warning(f"category '{path_str}' on host is structural, but it shouldn't be")

        category.part_category = part_category

    for part_category in part_categories.values():
        path_str = part_category.pathstring
        category_path = tuple(path_str.split("/"))
        if category_path in categories:
            continue

        for i in range(1, len(category_path)):
            if (parent := categories.get(category_path[:-i])) and parent.ignore:
                break
        else:
            warning(f"category '{path_str}' on host is not defined in {CATEGORIES_CONFIG}")

    parameter_templates = {
        parameter_template.name: parameter_template
        for parameter_template in ParameterTemplate.list(inventree_api)
    }

    for parameter in parameters.values():
        description, units = parameter.description, parameter.units

        if not (parameter_template := parameter_templates.get(parameter.name)):
            info(f"creating parameter template '{parameter.name}' ...")
            parameter_templates[parameter.name] = ParameterTemplate.create(inventree_api, {
                "name": parameter.name,
                "description": description,
                "units": units,
            })
        elif description != parameter_template.description or units != parameter_template.units:
            info(f"updating parameter template '{parameter.name}' ...")
            parameter_template.save({
                "description": parameter.description,
                "units": parameter.units,
            })

    for parameter_template in parameter_templates:
        if parameter_template not in used_parameters:
            warning(
                f"parameter template '{parameter_template}' on host "
                f"is not defined in {CATEGORIES_CONFIG}"
            )

    category_parameters = {
        (tuple(category.path), param)
        for category in categories.values() for param in category.parameters
    }
    part_category_parameter_templates = {
        (tuple(p.category_detail["pathstring"].split("/")), p.parameter_template_detail["name"])
        for p in PartCategoryParameterTemplate.list(inventree_api)
    }

    for category_parameter in category_parameters:
        if category_parameter not in part_category_parameter_templates:
            category_path, parameter = category_parameter
            category_str = "/".join(category_path)
            info(f"creating parameter template '{parameter}' for '{category_str}' ...")
            PartCategoryParameterTemplate.create(inventree_api, {
                "category": part_categories[category_path].pk,
                "parameter_template": parameter_templates[parameter].pk,
            })

    for part_category_path, template_name in part_category_parameter_templates:
        if (part_category_path, template_name) not in category_parameters:
            warning(
                f"parameter template '{template_name}' for '{'/'.join(part_category_path)}' "
                f"on host is not defined in {CATEGORIES_CONFIG}"
            )

    category_map = {}
    ignore = set()
    for category in categories.values():
        if category.structural or category.ignore:
            continue
        for alias in category.aliases:
            category_map[alias] = category
        if category.name not in ignore:
            if category.name not in category_map:
                category_map[category.name] = category
            else:
                ignore.add(category.name)
                category_map.pop(category.name)

    parameter_map = {}
    for parameter in parameters.values():
        for alias in (*parameter.aliases, parameter.name):
            if existing := parameter_map.get(alias):
                existing.append(parameter)
            else:
                parameter_map[alias] = [parameter]

    success("setup categories!", end="\n\n")

    return category_map, parameter_map

@dataclass
class Category:
    name: str
    path: list[str]
    description: str
    ignore: bool
    structural: bool
    aliases: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    part_category: PartCategory = None

    def __hash__(self):
        return hash(tuple(self.path))

    def add_alias(self, alias):
        self.aliases.append(alias)
        with update_config_file(CATEGORIES_CONFIG) as categories_config:
            category_config = categories_config
            try:
                for sub_category_name in self.path:
                    category_config = category_config[sub_category_name]

                if aliases := category_config.get("_aliases"):
                    aliases.append(alias)
                else:
                    categories_config["_aliases"] = [alias]

            except KeyError:
                warning(
                    f"failed to add alias '{alias}' for category '{self.name}' in "
                    f"'{CATEGORIES_CONFIG}'"
                )

CATEGORY_ATTRIBUTES = {"_parameters", "_description", "_ignore", "_structural", "_aliases"}
def parse_category_recursive(categories_dict, parameters=tuple(), path=tuple()):
    if not categories_dict:
        return {}

    categories = {}
    for name, values in categories_dict.items():
        if name.startswith("_"):
            continue

        if values is None:
            values = {}
        elif not isinstance(values, dict):
            warning(f"failed to parse category '{name}' (invalid type, should be dict or null)")
            continue

        for child in values.keys():
            if child.startswith("_") and child not in CATEGORY_ATTRIBUTES:
                warning(f"ignoring unknown special attribute '{child}' in category '{name}'")

        new_parameters = parameters + tuple(values.get("_parameters", []))
        new_path = path + (name,)

        categories[new_path] = Category(
            name=name,
            path=list(new_path),
            description=values.get("_description", name),
            ignore=values.get("_ignore", False),
            structural=values.get("_structural", False),
            aliases=values.get("_aliases", []),
            parameters=new_parameters,
        )

        categories.update(parse_category_recursive(values, new_parameters, new_path))

    return categories

@dataclass
class Parameter:
    name: str
    description: str
    aliases: list[str]
    units: str

PARAMETER_ATTRIBUTES = {"_description", "_aliases", "_unit"}
def parse_parameters(parameters_dict):
    if not parameters_dict:
        return {}

    parameters = {}
    for name, values in parameters_dict.items():
        if values is None:
            values = {}
        elif not isinstance(values, dict):
            warning(
                f"failed to parse parameter '{name}' (invalid type, should be dict or null)")
            continue

        for child in values.keys():
            if child.startswith("_") and child not in PARAMETER_ATTRIBUTES:
                warning(f"ignoring unknown special attribute '{child}' in parameter '{name}'")

        parameters[name] = Parameter(
            name=name,
            description=values.get("_description", name),
            aliases=values.get("_aliases", []),
            units=values.get("_unit", ""),
        )

    return parameters

def setup_config_from_inventree(inventree_api):
    info(f"copying categories and parameters configuration from '{inventree_api.base_url}' ...")
    categories = {
        part_category.pk: {
            "name": part_category.name,
            "parent": part_category.parent,
            "_description": part_category.description,
            "_structural": part_category.structural,
            "all_parameters": set(),
            "_parameters": set(),
        }
        for part_category in PartCategory.list(inventree_api)
    }

    parameters = {}
    for template in PartCategoryParameterTemplate.list(inventree_api):
        parameter_name = template.parameter_template_detail["name"]
        if parameter_name not in parameters:
            fields = {}
            if units := template.parameter_template_detail["units"]:
                fields["_unit"] = units
            if (desc := template.parameter_template_detail["description"]) != parameter_name:
                fields["_description"] = desc
            parameters[parameter_name] = fields

        if category := categories.get(template.category):
            category["all_parameters"].add(parameter_name)
            category["_parameters"].add(parameter_name)

    for _, category in categories.items():
        if parent_category := categories.get(category["parent"]):
            parent_category[category["name"]] = category
            category["_parameters"] -= parent_category["all_parameters"]

    for category in categories.values():
        if not category["_structural"]:
            del category["_structural"]
        if category["_description"] == category["name"]:
            del category["_description"]
        if category["parent"] is not None:
            del category["name"]
            del category["parent"]
        if category["_parameters"]:
            category["_parameters"] = sorted(category["_parameters"])
        else:
            del category["_parameters"]
        del category["all_parameters"]

    category_tree = {
        root_category["name"]: root_category
        for root_category in categories.values()
        if "parent" in root_category
    }

    for root_category in category_tree.values():
        del root_category["name"]
        del root_category["parent"]

    return category_tree, parameters
