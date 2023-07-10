from ..generic.Rules import set_rule
from .Regions import regionMap
from ..AutoWorld import World
from BaseClasses import MultiWorld
from .Items import item_name_to_id
from .Locations import location_name_to_id
import re


def infix_to_postfix(expr, location):
    prec = {"&": 2, "|": 2, "!": 3}

    stack = []
    postfix = ""

    try:
        for c in expr:
            if c.isnumeric():
                postfix += c
            elif c in prec:
                while stack and stack[-1] != "(" and prec[c] <= prec[stack[-1]]:
                    postfix += stack.pop()
                stack.append(c)
            elif c == "(":
                stack.append(c)
            elif c == ")":
                while stack and stack[-1] != "(":
                    postfix += stack.pop()
                stack.pop()
        while stack:
            postfix += stack.pop()
    except Exception:
        raise ValueError("Invalid logic format for location/region {}.".format(location)) 
    return postfix


def evaluate_postfix(expr, location):
    stack = []
    try:
        for c in expr:
            if c == "0":
                stack.append(False)
            elif c == "1":
                stack.append(True)
            elif c == "&":
                op2 = stack.pop()
                op1 = stack.pop()
                stack.append(op1 and op2)
            elif c == "|":
                op2 = stack.pop()
                op1 = stack.pop()
                stack.append(op1 or op2)
            elif c == "!":
                op = stack.pop()
                stack.append(not op)
    except Exception:
        raise ValueError("Invalid logic format for location/region {}.".format(location)) 
    
    if len(stack) != 1:
        raise ValueError("Invalid logic format for location/region {}.".format(location))
    return stack.pop()


def checkAccess(state, item, player):
    # split item into name and amount
    item_parts = item.split(":")
    item_name = item
    item_count = 1
    if len(item_parts) > 1:
        item_name = item_parts[0]
        item_count = int(item_parts[1])

    # if requires item, check if player has the amount of the item
    if item_name in item_name_to_id:
        if state.has(item_name, player, item_count):
            return True
        else:
            return False
    # if requires location check if player can access that location
    elif item_name in location_name_to_id:
        if state.can_reach(item_name, "Location", player):
            return True
        else:
            return False
    # with data validation this should never run
    else:
        raise ValueError("{} is not a valid item or location".format(item_name))


def set_rules(base: World, world: MultiWorld, player: int):
    # this is only called when the area (think, location or region) has a "requires" field that is a string
    def checkRequireStringForArea(state, area):
        # parse user written statement into list of each item
        requires_raw = re.split(r'(\|.*?\|)', area["requires"])

        requires_split = []
        for i in requires_raw:
            if i and i[0] == '|':
                requires_split.append(i[1:-1])
            else:
                requires_split.extend(re.split('(\AND|\)|\(|OR)', i))

        remove_spaces = [x.strip() for x in requires_split]
        requires_list = [x for x in remove_spaces if x != '']

        for i, item in enumerate(requires_list):
            if item.lower() == "or":
                requires_list[i] = "|"
            elif item.lower() == "and":
                requires_list[i] = "&"
            elif item == ")" or item == "(":
                continue
            else:
                if checkAccess(state, item, player):
                    requires_list[i] = "1"
                else:
                    requires_list[i] = "0"

        requires_string = infix_to_postfix("".join(requires_list), area)
        return (evaluate_postfix(requires_string, area))

    # this is only called when the area (think, location or region) has a "requires" field that is a dict
    def checkRequireDictForArea(state, area):
        canAccess = True

        for item in area["requires"]:
            # if the require entry is an object with "or" or a list of items, treat it as a standalone require of its own
            if (isinstance(item, dict) and "or" in item and isinstance(item["or"], list)) or (isinstance(item, list)):
                canAccessOr = True
                or_items = item
                
                if isinstance(item, dict):
                    or_items = item["or"]

                for or_item in or_items:
                    if not checkAccess(state, or_item, player):
                        canAccessOr = False

                if canAccessOr:
                    canAccess = True
                    break
            else:
                if not checkAccess(state, item, player):
                    canAccess = False

        return canAccess

    # handle any type of checking needed, then ferry the check off to a dedicated method for that check
    def fullLocationOrRegionCheck(state, area):
        # if it's not a usable object of some sort, default to true
        if not area:
            return True
        
        # don't require the "requires" key for locations and regions if they don't need to use it
        if "requires" not in area.keys():
            return True
        
        if isinstance(area["requires"], str):
            return checkRequireStringForArea(state, area)
        else:  # item access is in dict form
            return checkRequireDictForArea(state, area)
    
    # Region access rules
    for region in regionMap.keys():
        if region != "Menu":
            for exitRegion in world.get_region(region, player).exits:
                def fullRegionCheck(state, region=regionMap[region]):
                    return fullLocationOrRegionCheck(state, region)
                
                set_rule(world.get_entrance(exitRegion.name, player), fullRegionCheck)    

    # Location access rules
    for location in base.location_table:
        locFromWorld = world.get_location(location["name"], player)

        locationRegion = regionMap[location["region"]] if "region" in location else None
        
        if "requires" in location: # Location has requires, check them alongside the region requires
            def checkBothLocationAndRegion(state, location=location, region=locationRegion):
                locationCheck = fullLocationOrRegionCheck(state, location)
                regionCheck = True # default to true unless there's a region with requires

                if region:
                    regionCheck = fullLocationOrRegionCheck(state, region)

                return locationCheck and regionCheck
            
            set_rule(locFromWorld, checkBothLocationAndRegion)
        elif "region" in location: # Only region access required, check the location's region's requires
            def fullRegionCheck(state, region=locationRegion):
                return fullLocationOrRegionCheck(state, region)
            
            set_rule(locFromWorld, fullRegionCheck)
        else: # No location region and no location requires? It's accessible.
            def allRegionsAccessible(state):
                return True
            
            set_rule(locFromWorld, allRegionsAccessible)

    # Victory requirement
    world.completion_condition[player] = lambda state: state.has("__Victory__", player)
