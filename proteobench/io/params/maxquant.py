"""Functionality to parse Maxqunt mqpar.xml parameter files"""
from __future__ import annotations

import collections
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from proteobench.io.params import ProteoBenchParameters

logger = logging.getLogger()


def extend_tuple(t, target_length: int):
    """Extend tuple with None values to match target length."""
    if not isinstance(t, tuple):
        raise TypeError(f"Wrong type provided. Expected tuple, got {type(t)} : {t!r}")
    if len(t) > target_length:
        raise ValueError(
            f"Tuple is too long (got {len(t)}, expected {target_length}: {t!r}"
        )
    return t + (None,) * (target_length - len(t))


def extend_tuples_with_none(list_of_tuples: list[tuple], target_length: int):
    """Extend the tuples in a list of tuples with None values to match target length."""
    extended_tuples = []
    for tuple_ in list_of_tuples:
        # if len(tuple_) > target_length:
        #     raise ValueError(f"tuple is too long: {len(tuple_)}")
        extended_tuple = extend_tuple(tuple_, target_length)
        extended_tuples.append(extended_tuple)
    return extended_tuples


def add_record(data: dict, tag: str, record) -> dict:
    """Add tag and record to data dict.

    The record can be many things."""
    if tag in data:
        if isinstance(data[tag], list):
            data[tag].append(record)
        else:
            data[tag] = [data[tag], record]
    else:
        data[tag] = record
    return data


def read_xml_record(element: ET.Element) -> dict:
    """Read entire record in a nested dict structure."""
    data = dict()
    for child in element:
        if len(child) > 1 and child.tag:
            # if there is a list, process each element one by one
            # either nested or a plain text
            data[child.tag] = [
                add_record(
                    dict(),
                    tag=child.tag,
                    record=read_xml_record(child)
                    if not (child.text and child.text.strip())
                    else child.text.strip(),
                )
                for child in child
            ]
        elif child.text and child.text.strip():
            # just plain text record
            data = add_record(data=data, tag=child.tag, record=child.text.strip())
        else:
            record = read_xml_record(child)
            data = add_record(data, child.tag, record)
    if not data:
        # empty strings and None are normalzied to None
        return None
    return data


def read_file(file: str) -> dict:
    """Read all entries in a MaxQuant xml file."""
    tree: ET.ElementTree = ET.parse(file)
    root: ET.Element = tree.getroot()
    params: dict = read_xml_record(root)
    return params


def flatten_dict_of_dicts(d: dict, parent_key: str = "") -> dict:
    """Build tuples for nested dictionaries for use as `pandas.MultiIndex`.

    Parameters
    ----------
    d : dict
        Nested dictionary for which all keys are flattened to tuples.
    parent_key : str, optional
        Outer key (used for recursion), by default ''

    Returns
    -------
    dict
        Flattend dictionary with tuple keys: {(outer_key, ..., inner_key) : value}
    """
    # simplified and adapted from: https://stackoverflow.com/a/6027615/9684872
    items = []
    for k, v in d.items():
        new_key = parent_key + (k,) if parent_key else (k,)
        if isinstance(v, collections.abc.MutableMapping):
            items.extend(flatten_dict_of_dicts(v, parent_key=new_key))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, collections.abc.MutableMapping):
                    items.extend(flatten_dict_of_dicts(item, parent_key=new_key))
                elif isinstance(item, str):
                    items.append((new_key, item))
                else:
                    raise ValueError(f"Unknown item: {item:r}")
        else:
            items.append((new_key, v))
    return items


def build_Series_from_records(records, index_length=4):
    records = flatten_dict_of_dicts(records)
    idx = pd.MultiIndex.from_tuples(
        (extend_tuple(k, index_length) for (k, v) in records)
    )
    return pd.Series((v for (k, v) in records), index=idx)


# %%
def extract_params(fname) -> ProteoBenchParameters:
    params = ProteoBenchParameters()

    record = read_file(fname)
    record = build_Series_from_records(record, 4).sort_index()
    params.search_engine = "Andromeda"
    params.software_version = record.loc["maxQuantVersion"].squeeze()
    params.ident_fdr_psm = None
    params.ident_fdr_peptide = record.loc["peptideFdr"].squeeze()
    params.ident_fdr_protein = record.loc["proteinFdr"].squeeze()
    params.enable_match_between_runs = record.loc["matchBetweenRuns"].squeeze()
    precursor_mass_tolerance = record.loc[
        pd.IndexSlice["parameterGroups", "parameterGroup", "mainSearchTol", :]
    ].squeeze()
    params.precursor_mass_tolerance = f"{precursor_mass_tolerance} ppm"
    fragment_mass_tolerance = None  # ! differences between version >1.6 and <=1.5
    params.fragment_mass_tolerance = fragment_mass_tolerance
    params.enzyme = record.loc[
        ("parameterGroups", "parameterGroup", "enzymes", "string")
    ].squeeze()
    params.allowed_miscleavages = record.loc[
        pd.IndexSlice["parameterGroups", "parameterGroup", "maxMissedCleavages", :]
    ].squeeze()
    params.min_peptide_length = record.loc["minPepLen"].squeeze()
    params.max_peptide_length = None
    # fixed mods
    if params.software_version > "1.6.0.0":
        fixed_mods = record.loc[
            pd.IndexSlice["parameterGroups", "parameterGroup", "fixedModifications", :]
        ].squeeze()
        if isinstance(fixed_mods, str):
            params.fixed_mods = fixed_mods
        else:
            params.fixed_mods = ",".join(fixed_mods)
    else:
        fixed_mods = record.loc[
            pd.IndexSlice["fixedModifications", :]
        ].squeeze()
        if isinstance(fixed_mods, str):
            params.fixed_mods = fixed_mods
        else:
            params.fixed_mods = ",".join(fixed_mods)

    variable_mods = record.loc[
        pd.IndexSlice["parameterGroups", "parameterGroup", "variableModifications", :]
    ].squeeze()
    if isinstance(variable_mods, str):
        params.variable_mods = variable_mods
    else:
        params.variable_mods = ",".join(variable_mods)
    params.max_mods = record.loc[
        ("parameterGroups", "parameterGroup", "maxNmods")
    ].squeeze()
    params.min_precursor_charge = None
    params.max_precursor_charge = record.loc[
        pd.IndexSlice["parameterGroups", "parameterGroup", "maxCharge", :]
    ].squeeze()
    return params


# create a first version of json files to match
if __name__ == "__main__":
    from pprint import pprint

    for test_file in [
        "../../../test/params/mqpar_MQ1.6.3.3_MBR.xml",
        "../../../test/params/mqpar_MQ2.1.3.0_noMBR.xml",
        "../../../test/params/mqpar1.5.3.30_MBR.xml",
    ]:
        print(f"{test_file = }")
        record = read_file(test_file)
        (
            Path(test_file)
            .with_suffix(".json")
            .write_text(
                json.dumps(
                    record,
                    indent=4,
                )
            )
        )
        record = build_Series_from_records(record, 4)
        record = record.to_frame("run_identifier")
        # flattend.to_csv(Path(test_file).with_suffix(".csv"))
        params = extract_params(test_file)
        pprint(params.__dict__)
