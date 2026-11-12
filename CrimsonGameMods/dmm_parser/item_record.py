# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser

"""ItemInfo record reader for the 2.04.00 wire order.

The packaged native extension reads records in the pre-2.04 order (key first,
then the name), so it desyncs on current game data. Build 2.04.00 reordered the
record: name, key, the one-byte flags, then keys/numbers, then strings, lists
and sub-structs. Field order below is the game's 2.04 reader.

Row boundaries come from the table header (`.staticinfoheader`): a u16 row count
followed by `(key, body_offset)` pairs. Parsing a record must land exactly on the
next row's offset - `check_boundaries()` uses that as the layout proof.
"""

from __future__ import annotations

import struct

def _u8(b, p):
    return b[p], p + 1

def _u16(b, p):
    return struct.unpack_from('<H', b, p)[0], p + 2

def _u32(b, p):
    return struct.unpack_from('<I', b, p)[0], p + 4

def _u64(b, p):
    return struct.unpack_from('<Q', b, p)[0], p + 8

def _i64(b, p):
    return struct.unpack_from('<q', b, p)[0], p + 8

def _f32(b, p):
    return struct.unpack_from('<f', b, p)[0], p + 4

def _i8(b, p):
    return struct.unpack_from('<b', b, p)[0], p + 1

def _cstr(b, p):
    n = struct.unpack_from('<I', b, p)[0]
    p += 4
    if p + n > len(b):
        raise ValueError(f"string length {n} runs past the buffer at {p - 4:#x}")
    return b[p:p + n].decode('utf-8', 'replace'), p + n

def _lstr(b, p):
    category, p = _u8(b, p)
    index, p = _u64(b, p)
    default, p = _cstr(b, p)
    return {'category': category, 'index': index, 'default': default}, p

def _array(elem):
    def read(b, p):
        count = struct.unpack_from('<I', b, p)[0]
        p += 4
        if count > len(b) - p:
            raise ValueError(f"CArray count {count} exceeds remaining bytes {len(b) - p} at {p - 4:#x}")
        items = []
        for _ in range(count):
            value, p = elem(b, p)
            items.append(value)
        return items, p
    return read

def _optional(inner):
    def read(b, p):
        flag, p = _u8(b, p)
        return (None, p) if flag == 0 else inner(b, p)
    return read

def _fixed32(elem, n):
    def read(b, p):
        out = []
        for _ in range(n):
            value, p = elem(b, p)
            out.append(value)
        return out, p
    return read

SUBITEM_NONE = {14, 15, 16, 17, 18, 255}

def _subitem(b, p):
    type_id, p = _u8(b, p)
    if type_id in SUBITEM_NONE:
        return {'type_id': type_id, 'value': None}, p
    if type_id in (0, 3, 9):
        value, p = _u32(b, p)
        return {'type_id': type_id, 'value': value}, p
    raise ValueError(f"unknown SubItem type {type_id} at {p - 1:#x}")

def _sealable(b, p):
    type_tag, p = _u8(b, p)
    item_key, p = _u32(b, p)
    unknown0, p = _u64(b, p)
    if type_tag in (0, 1, 3, 4):
        value, p = _u32(b, p)
    elif type_tag == 2:
        value, p = _cstr(b, p)
    else:
        raise ValueError(f"unknown SealableItemInfo type {type_tag} at {p - 1:#x}")
    return {'type_tag': type_tag, 'item_key': item_key, 'unknown0': unknown0, 'value': value}, p

def _enchant_stat_change(b, p):
    stat, p = _u32(b, p)
    change, p = _i64(b, p)
    return {'stat': stat, 'change_mb': change}, p

def _enchant_level_change(b, p):
    stat, p = _u32(b, p)
    change, p = _i8(b, p)
    return {'stat': stat, 'change_mb': change}, p

def _enchant_stat_data(b, p):  # noqa: F811 - replace placeholder with real field order
    out = {}
    for name, elem in (('max_stat_list', _enchant_stat_change),
                       ('regen_stat_list', _enchant_stat_change),
                       ('stat_list_static', _enchant_stat_change),
                       ('stat_list_static_level', _enchant_level_change)):
        out[name], p = _array(elem)(b, p)
    return out, p

def _price_floor(b, p):
    price, p = _u64(b, p)
    sym_no, p = _u32(b, p)
    item_info_wrapper, p = _u32(b, p)
    return {'price': price, 'sym_no': sym_no, 'item_info_wrapper': item_info_wrapper}, p

def _item_price_info(b, p):
    key, p = _u32(b, p)
    price, p = _price_floor(b, p)
    return {'key': key, 'price': price}, p

def _occupied_equip_slot_data(b, p):
    name_key, p = _u32(b, p)
    index_list, p = _array(_u8)(b, p)
    return {'equip_slot_name_key': name_key, 'equip_slot_name_index_list': index_list}, p

def _item_icon_data(b, p):
    icon_path, p = _u32(b, p)
    highlight, p = _u32(b, p)
    sealed, p = _u8(b, p)
    states, p = _array(_u32)(b, p)
    usable, p = _u8(b, p)
    return {'icon_path': icon_path, 'highlight_icon_path': highlight,
            'check_exist_sealed_data': sealed, 'gimmick_state_list': states,
            'check_usable': usable}, p

def _passive_skill_level(b, p):
    skill, p = _u32(b, p)
    level, p = _u32(b, p)
    return {'skill': skill, 'level': level}, p

def _reserve_slot_target_data(b, p):
    slot, p = _u32(b, p)
    condition, p = _u32(b, p)
    return {'reserve_slot_info': slot, 'condition_info': condition}, p

def _socket_material_item(b, p):
    item, p = _u32(b, p)
    value, p = _u64(b, p)
    return {'item': item, 'value': value}, p

def _equipment_buff(b, p):
    buff, p = _u32(b, p)
    level, p = _u32(b, p)
    return {'buff': buff, 'level': level}, p

def _enchant_data(b, p):
    level, p = _u16(b, p)
    stat_data, p = _enchant_stat_data(b, p)
    buy, p = _array(_item_price_info)(b, p)
    buffs, p = _array(_equipment_buff)(b, p)
    passive, p = _array(_equipment_buff)(b, p)
    unk, p = _u32(b, p)
    return {'level': level, 'enchant_stat_data': stat_data, 'buy_price_list': buy,
            'equip_buffs': buffs, 'equip_passive_buffs': passive, 'unk_u32_112': unk}, p

def _game_event_execute_data(b, p):
    event_type, p = _u8(b, p)
    player, p = _u32(b, p)
    target, p = _u32(b, p)
    condition, p = _u32(b, p)
    return {'game_event_type': event_type, 'player_condition': player,
            'target_condition': target, 'event_condition': condition}, p

def _inventory_change_data(b, p):
    event, p = _game_event_execute_data(b, p)
    inventory, p = _u16(b, p)
    return {'game_event_execute_data': event, 'to_inventory_info': inventory}, p

def _page_data(b, p):
    left, p = _cstr(b, p)
    right, p = _cstr(b, p)
    left_knowledge, p = _u32(b, p)
    right_knowledge, p = _u32(b, p)
    return {'left_page_texture_path': left, 'right_page_texture_path': right,
            'left_page_related_knowledge_info': left_knowledge,
            'right_page_related_knowledge_info': right_knowledge}, p

def _inspect_data(b, p):
    out = {}
    for name, reader in (('item_info', _u32), ('gimmick_info', _u32), ('character_info', _u32),
                         ('spawn_reason_hash', _u32), ('socket_name', _cstr),
                         ('speak_character_info', _u32), ('inspect_target_tag', _u32),
                         ('reward_own_knowledge', _u8), ('reward_knowledge_info', _u32),
                         ('item_desc', _lstr), ('board_key', _u32),
                         ('inspect_action_type', _u8), ('gimmick_state_name_hash', _u32),
                         ('target_page_index', _u32), ('is_left_page', _u8),
                         ('target_page_related_knowledge_info', _u32),
                         ('enable_read_after_reward', _u8), ('refer_to_left_page_inspect_data', _u8),
                         ('inspect_effect_info_key', _u32), ('inspect_complete_effect_info_key', _u32),
                         ('extract_max_distance_from_socket', _f32), ('extract_align_max_angle', _f32)):
        out[name], p = reader(b, p)
    return out, p

def _inspect_action(b, p):
    action_hash, p = _u32(b, p)
    catch_hash, p = _u32(b, p)
    catcher, p = _cstr(b, p)
    target, p = _cstr(b, p)
    return {'action_name_hash': action_hash, 'catch_tag_name_hash': catch_hash,
            'catcher_socket_name': catcher, 'catch_target_socket_name': target}, p

def _sharpness_data(b, p):
    max_sharpness, p = _u16(b, p)
    craft_tool, p = _u16(b, p)
    stat_data, p = _enchant_stat_data(b, p)
    return {'max_sharpness': max_sharpness, 'craft_tool_info': craft_tool,
            'stat_data': stat_data}, p

def _item_bundle_data(b, p):
    count_mb, p = _u64(b, p)
    key, p = _u32(b, p)
    return {'count_mb': count_mb, 'key': key}, p

def _unit_data(b, p):
    component, p = _cstr(b, p)
    minimum, p = _u32(b, p)
    icon, p = _u32(b, p)
    unk_hash, p = _u32(b, p)
    item_name, p = _lstr(b, p)
    item_desc, p = _lstr(b, p)
    return {'ui_component': component, 'minimum': minimum, 'icon_path': icon,
            'unk_hash_110': unk_hash, 'item_name': item_name, 'item_desc': item_desc}, p

def _money_unit_entry(b, p):
    key, p = _u32(b, p)
    value, p = _unit_data(b, p)
    return {'key': key, 'value': value}, p

def _money_type_define(b, p):
    floor_value, p = _u64(b, p)
    units, p = _array(_money_unit_entry)(b, p)
    return {'price_floor_value': floor_value, 'unit_data_list_map': units}, p

def _pattern_param_string(b, p):
    flag, p = _u8(b, p)
    category, p = _u8(b, p)
    index, p = _u64(b, p)
    param, p = _cstr(b, p)
    return {'flag': flag, 'category': category, 'index': index, 'param_string': param}, p

def _pattern_description_data(b, p):
    info, p = _u32(b, p)
    params, p = _array(_pattern_param_string)(b, p)
    return {'pattern_description_info': info, 'param_string_list': params}, p

def _faction_management_data(b, p):
    faction, p = _u32(b, p)
    a, p = _u64(b, p)
    b_, p = _u64(b, p)
    c, p = _u64(b, p)
    return {'faction_info': faction, 'value_a': a, 'value_b': b_, 'value_c': c}, p

def _faction_management(b, p):
    is_valid, p = _u8(b, p)
    cost, p = _array(_faction_management_data)(b, p)
    price, p = _array(_faction_management_data)(b, p)
    tier, p = _u32(b, p)
    synergy, p = _array(_u16)(b, p)
    return {'is_valid': is_valid, 'cost_list': cost, 'price_list': price,
            'tier': tier, 'synergy_list': synergy}, p

def _repair_data(b, p):
    resource, p = _u32(b, p)
    value, p = _u16(b, p)
    style, p = _u8(b, p)
    count, p = _u64(b, p)
    return {'resource_item_info': resource, 'repair_value': value,
            'repair_style': style, 'resource_item_count': count}, p

def _drop_default_data(b, p):
    enchant_level, p = _u16(b, p)
    sockets, p = _array(_u32)(b, p)
    materials, p = _array(_socket_material_item)(b, p)
    sub_item, p = _subitem(b, p)
    socket_count, p = _u8(b, p)
    use_socket, p = _u8(b, p)
    return {'drop_enchant_level': enchant_level, 'socket_item_list': sockets,
            'add_socket_material_item_list': materials, 'default_sub_item': sub_item,
            'socket_valid_count': socket_count, 'use_socket': use_socket}, p

def _prefab_data(b, p):
    scale, p = _fixed32(_f32, 3)(b, p)
    names, p = _array(_u32)(b, p)
    animations, p = _array(_u32)(b, p)
    slots, p = _array(_u16)(b, p)
    tribes, p = _array(_u32)(b, p)
    docking_switch, p = _u32(b, p)
    use_gimmick, p = _u8(b, p)
    craft_material, p = _u8(b, p)
    data_type, p = _u8(b, p)
    return {'scale': scale, 'prefab_names': names, 'animation_path_list': animations,
            'equip_slot_list': slots, 'tribe_gender_list': tribes,
            'docking_prefab_switch_name': docking_switch, 'use_gimmick_prefab': use_gimmick,
            'is_craft_material': craft_material, 'prefab_data_type': data_type}, p

def _docking_tag4(b, p):
    return _fixed32(_u32, 4)(b, p)

def _docking_child_data(b, p):
    out = {}
    readers = [
        ('gimmick_info_key', _u32), ('character_key', _u32), ('item_key', _u32),
        ('attach_parent_socket_name', _cstr), ('attach_child_socket_name', _cstr),
        ('docking_tag_name_hash', _docking_tag4), ('docking_equip_slot_no', _u16),
        ('spawn_distance_level', _u32), ('is_item_equip_docking_gimmick', _u8),
        ('send_damage_to_parent', _u8), ('is_body_part', _u8), ('docking_type', _u8),
        ('is_summoner_team', _u8), ('is_player_only', _u8), ('player_condition', _u32),
        ('owner_condition', _u32), ('is_sync_break_parent', _u8), ('hit_part', _u8),
        ('detected_by_npc', _u8), ('is_bag_docking', _u8), ('enable_collision', _u8),
        ('disable_collision_with_other_gimmick', _u8), ('docking_slot_key', _cstr),
        ('inherit_summoner', _u8), ('summon_tag_name_hash', _docking_tag4),
        ('animation_root_bone_name', _cstr), ('use_cool_time', _u8),
    ]
    for name, reader in readers:
        out[name], p = reader(b, p)
    return out, p

FLAGS = [
    'is_reward_loot_drop', 'lost_item_recovery_type', 'is_editable_grime', 'is_dyeable',
    'discardable', 'use_average_price', 'is_housing_only', 'is_destroy_when_broken',
    'discard_attach_terrain', 'is_blocked_store_sell', 'enable_equip_in_clone_actor',
    'is_logout_at_use_item', 'is_preserved_on_extract', 'is_has_item_use_data_inventory_buff',
    'is_preorder_item', 'is_tower_shield_item', 'is_shield_item',
    'hide_from_inventory_on_pop_item', 'is_save_game_data_at_use_item',
    'enable_alert_system_to_ui', 'is_wild', 'is_editor_usable', 'use_map_icon_alert',
    'is_extract_able_item', 'use_immediately', 'apply_max_stack_cap',
    'is_all_gimmick_sealable', 'is_register_trade_market', 'can_disassemble',
    'delete_by_gimmick_unlock', 'use_drop_set_target', 'item_type',
    'knowledge_obtain_type', 'item_tier', 'usable_alert_type', 'item_charge_type',
    'apply_drop_stat_type',
]

FIELDS = [
    ('string_key', _cstr),
    ('key', _u32),
    ('is_blocked', _u8),
    ('max_endurance', _u16),
    ('max_stack_count', _u64),
    *[(name, _u8) for name in FLAGS],
    ('look_detail_mission_info', _u32),
    ('look_detail_game_advice_info_wrapper', _u32),
    ('convert_item_info_by_drop_npc', _u32),
    ('unpacked_item_info', _u32),
    ('item_effect_info', _u32),
    ('broken_item_prefix_string', _u32),
    ('equip_type_info', _u32),
    ('material_match_info', _u32),
    ('map_icon_path', _u32),
    ('packed_item_info', _u32),
    ('gimmick_info', _u32),
    ('destroy_effec_info', _u32),
    ('extract_additional_drop_set_info', _u32),
    ('minimum_extract_enchant_level', _u16),
    ('category_info', _u16),
    ('gimmick_unlock_message_local_string_info', _u32),
    ('knowledge_info', _u32),
    ('max_drop_result_sub_item_count', _u32),
    ('equipable_hash', _u32),
    ('default_sub_item', _subitem),
    ('discard_offset_y', _f32),
    ('stage_info', _u32),
    ('material_key', _u32),
    ('shared_cool_time_group_name_hash', _u32),
    ('equipable_level', _u32),
    ('max_charged_useable_count', _fixed32(_u32, 3)),
    ('item_name', _lstr),
    ('item_desc', _lstr),
    ('item_desc2', _optional(_lstr)),
    ('item_memo', _cstr),
    ('filter_type', _cstr),
    ('sound_name_on_max_charged', _cstr),
    ('sound_socket_name_on_max_charged', _cstr),
    ('unk_texture_path', _u32),
    ('emoji_texture_id', _u32),
    ('occupied_equip_slot_data_list', _optional(_array(_occupied_equip_slot_data))),
    ('item_tag_list', _optional(_array(_u32))),
    ('item_use_info_list', _optional(_array(_u32))),
    ('item_icon_list', _array(_item_icon_data)),
    ('equip_passive_skill_list', _optional(_array(_passive_skill_level))),
    ('gimmick_tag_list', _optional(_array(_cstr))),
    ('sealable_item_info_list', _optional(_array(_sealable))),
    ('sealable_character_info_list', _optional(_array(_sealable))),
    ('sealable_gimmick_info_list', _optional(_array(_sealable))),
    ('sealable_gimmick_tag_list', _optional(_array(_sealable))),
    ('sealable_tribe_info_list', _optional(_array(_sealable))),
    ('sealable_money_info_list', _optional(_array(_u32))),
    ('transmutation_material_gimmick_list', _optional(_array(_u32))),
    ('transmutation_material_item_list', _optional(_array(_u32))),
    ('transmutation_material_item_group_list', _optional(_array(_u16))),
    ('multi_change_info_list', _optional(_array(_u32))),
    ('reserve_slot_target_data_list', _optional(_array(_reserve_slot_target_data))),
    ('drop_default_data', _optional(_drop_default_data)),
    ('enchant_data_list', _optional(_array(_enchant_data))),
    ('price_list', _array(_item_price_info)),
    ('docking_child_data', _optional(_docking_child_data)),
    ('change_character_docking_child_data_list', _optional(_array(_docking_child_data))),
    ('inventory_change_data', _optional(_inventory_change_data)),
    ('fixed_page_data_list', _optional(_array(_page_data))),
    ('dynamic_page_data_list', _optional(_array(_page_data))),
    ('inspect_data_list', _optional(_array(_inspect_data))),
    ('inspect_action', _optional(_inspect_action)),
    ('cooltime', _optional(_fixed32(_i64, 3))),
    ('sharpness_data', _optional(_sharpness_data)),
    ('hackable_character_group_info_list', _optional(_array(_u16))),
    ('item_group_info_list', _array(_u16)),
    ('pattern_description_data_list', _optional(_array(_pattern_description_data))),
    ('item_bundle_data_list', _optional(_array(_item_bundle_data))),
    ('money_type_define', _optional(_money_type_define)),
    ('faction_management_data', _optional(_faction_management)),
    ('respawn_time_seconds', _i64),
    ('repair_data_list', _optional(_array(_repair_data))),
    ('prefab_data_list', _array(_prefab_data)),
    *[(f'push_inventory_type_{i}_116', _u16) for i in range(8)],
    ('item_push_inventory_contents_type_113', _u8),
    ('trailing_u8_113', _u8),
    ('push_inventory_type_8_203', _u16),
    ('push_inventory_type_9_204', _u16),
    ('push_inventory_type_10_204', _u16),
]


def read_record(body: bytes, start: int) -> tuple[dict, int]:
    record = {}
    pos = start
    for name, reader in FIELDS:
        value, pos = reader(body, pos)
        record[name] = value
    return record, pos


def read_header(header: bytes) -> list[tuple[int, int]]:
    """(key, body offset) for every row, in table order."""
    count = struct.unpack_from('<H', header, 0)[0]
    if 2 + count * 8 != len(header):
        raise ValueError(f"header size {len(header)} does not match {count} rows")
    return [struct.unpack_from('<II', header, 2 + i * 8) for i in range(count)]


def check_boundaries(header: bytes, body: bytes) -> list[tuple[int, int, int]]:
    """Rows whose parse does not land on the next row start: (key, expected, got)."""
    rows = read_header(header)
    bad = []
    for i, (key, offset) in enumerate(rows):
        expected = rows[i + 1][1] if i + 1 < len(rows) else len(body)
        try:
            _, pos = read_record(body, offset)
        except (ValueError, struct.error, IndexError) as exc:
            bad.append((key, expected, -1))
            continue
        if pos != expected:
            bad.append((key, expected, pos))
    return bad
