import os
from typing import cast

import matplotlib.pyplot as plt
import pandas as pd
import pyro
import torch
from imageio import imwrite

from ..logging import WARNING, log
from ..model.experiment.st.st import ST, _encode_metagene_name
from ..session import Session, require
from ..utility.visualization import visualize_metagenes
from .analyze import Analysis, _register_analysis

__all__ = [
    "compute_metagene_profiles",
    "compute_metagene_summary",
    "visualize_metagene_profile",
]


def compute_metagene_profiles():
    r"""Computes metagene profiles"""
    model = require("model")
    genes = require("genes")

    def _metagene_profile_st():
        model = require("model")
        experiment = cast(ST, model.get_experiment("ST"))
        with pyro.poutine.block():
            with pyro.poutine.trace() as trace:
                # pylint: disable=protected-access
                experiment._sample_globals()
        return [
            (n, trace.trace.nodes[_encode_metagene_name(n)]["fn"])
            for n in experiment.metagenes
        ]

    _metagene_profile_fn = {"ST": _metagene_profile_st}

    for experiment in model.experiments.keys():
        try:
            names, profiles = zip(*_metagene_profile_fn[experiment]())
            dataframe = (
                pd.concat(
                    [
                        pd.DataFrame(
                            [
                                x.mean.detach().cpu().numpy(),
                                x.stddev.detach().cpu().numpy(),
                            ],
                            columns=genes,
                            index=pd.Index(["mean", "stddev"], name="type"),
                        )
                        for x in profiles
                    ],
                    keys=pd.Index(names, name="metagene"),
                )
                .reset_index()
                .melt(
                    ["metagene", "type"],
                    var_name="gene",
                    value_name="log2fold",
                )
            )
            yield experiment, dataframe
        except KeyError:
            log(
                WARNING,
                'Metagene profiles for experiment of type "%s" '
                " not implemented",
                experiment,
            )
            continue


def visualize_metagene_profile(profile, num_high=20, num_low=20, ax=None):
    r"""Creates metagene profile visualization"""
    x = profile.pivot("gene", "type", "log2fold")
    x = x.sort_values("mean")
    x = pd.concat([x.iloc[:num_low], x.iloc[-num_high:]])
    (ax if ax else plt).errorbar(
        x["mean"], x.index, xerr=x["stddev"], fmt="none", c="black"
    )
    (ax if ax else plt).vlines(
        0.0,
        ymin=x.index[0],
        ymax=x.index[-1],
        colors="red",
        linestyles="--",
        lw=1,
    )


def compute_metagene_summary(method: str = "pca") -> None:
    r"""Imputation analysis function"""
    # pylint: disable=too-many-locals
    dataloader = require("dataloader")
    save_path = require("save_path")

    output_dir = os.path.join(save_path, f"metagenes")
    os.makedirs(output_dir, exist_ok=True)

    with Session(
        default_device=torch.device("cpu"), pyro_stack=[]
    ), torch.no_grad():
        for slide_path, (summarization, metagenes) in zip(
            dataloader.dataset.data.design.columns,
            visualize_metagenes(method),
        ):
            slide_name = os.path.basename(slide_path)
            os.makedirs(os.path.join(output_dir, slide_name), exist_ok=True)
            imwrite(
                os.path.join(output_dir, slide_name, "summary.png"),
                summarization,
            )
            for name, metagene in metagenes:
                imwrite(
                    os.path.join(
                        output_dir, slide_name, f"metagene-{name}.png"
                    ),
                    metagene,
                )

        for experiment, metagene_profiles in compute_metagene_profiles():
            metagene_profiles.to_csv(
                os.path.join(output_dir, f"{experiment}-metagenes.csv.gz"),
                index=False,
            )
            for metagene in metagene_profiles.metagene.unique():
                plt.figure(figsize=(4, 14))
                visualize_metagene_profile(
                    metagene_profiles[metagene_profiles.metagene == metagene],
                    num_high=40,
                    num_low=40,
                )
                plt.title(f"{metagene=} ({experiment})")
                plt.tight_layout(pad=0.0)
                plt.savefig(
                    os.path.join(
                        output_dir, f"{experiment}-metagene-{metagene}.png"
                    ),
                    dpi=600,
                )
                plt.close()


_register_analysis(
    name="metagenes",
    analysis=Analysis(
        description="Creates summary data of the metagenes",
        function=compute_metagene_summary,
    ),
)
