from dataclasses import dataclass, field

from inventree.part import PartCategory, ParameterTemplate, PartCategoryParameterTemplate

from .config import (
    get_categories_config, get_parameters_config, CATEGORIES_CONFIG, PARAMETERS_CONFIG,
)
from .error_helper import *

def setup_categories_and_parameters(inventree_api):
    info("setting up categories ...")

    categories_config = get_categories_config()
    categories = parse_category_recursive(categories_config)

    parameters_config = get_parameters_config()
    parameters = parse_parameters(parameters_config)

    used_parameters = set.union(*[set(category.parameters) for category in categories.values()])

    for parameter in used_parameters:
        if parameter not in parameters:
            error(f"parameter '{parameter}' not defined in {PARAMETERS_CONFIG.name}")
            return None, None
        if not parameter in used_parameters:
            warning(f"parameter '{parameter}' is defined, but not being used")

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
            warning(f"category '{path_str}' on host is not defined in {CATEGORIES_CONFIG.name}")

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
        if parameter_template not in parameters:
            warning(
                f"parameter template '{parameter_template}' on host "
                f"is not defined in {CATEGORIES_CONFIG.name}"
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
        if not category_parameter in part_category_parameter_templates:
            category_path, parameter = category_parameter
            category_str = "/".join(category_path)
            info(f"creating parameter template '{parameter}' for '{category_str}' ...")
            PartCategoryParameterTemplate.create(inventree_api, {
                "category": part_categories[category_path].pk,
                "parameter_template": parameter_templates[parameter].pk,
            })

    for part_category, parameter_template in part_category_parameter_templates:
        if (part_category, parameter_template) not in category_parameters:
            warning(
                f"parameter template '{parameter_template}' for '{'/'.join(part_category)}' "
                f"on host is not defined in {CATEGORIES_CONFIG.name}")

    category_map = {}
    ignore = set()
    for category in categories.values():
        for alias in category.aliases:
            category_map[alias] = category
        if category.name in category_map:
            ignore.add(category.name)
            category_map.pop(category.name)
        elif category.name not in ignore:
            category_map[category.name] = category

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

def parse_category_recursive(categories_dict, parameters=tuple(), path=tuple()):
    categories = {}
    for key, value in categories_dict.items():
        if key.startswith("_"):
            continue

        if value is None:
            value = {}

        new_parameters = parameters + tuple(value.get("_parameters", []))
        new_path = path + (key,)

        categories[new_path] = Category(
            name=key,
            path=list(new_path),
            description=value.get("_description", key),
            ignore=value.get("_ignore", False),
            structural=value.get("_structural", False),
            aliases=value.get("_aliases", []),
            parameters=new_parameters,
        )

        categories.update(parse_category_recursive(value, new_parameters, new_path))

    return categories

@dataclass
class Parameter:
    name: str
    description: str
    aliases: list[str]
    units: str

def parse_parameters(parameters_dict):
    parameters = {}
    for parameter, values in parameters_dict.items():
        if parameter.startswith("_"):
            continue

        if values is None:
            values = {}

        parameters[parameter] = Parameter(
            name=parameter,
            description=values.get("_description", parameter),
            aliases=values.get("_aliases", []),
            units=values.get("_unit", ""),
        )

    return parameters
