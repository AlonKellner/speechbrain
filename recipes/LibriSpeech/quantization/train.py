"""
Recipe  to train K-means clustering model on self-supervised representations.

To run this recipe, do the following:
> python train.py hparams/train_with_[SSL-model].yaml --data_folder=/path/to/LibriSPeech
Author
 * Pooneh Mousavi 2023
"""

import logging
import os
import sys

import torchaudio
from hyperpyyaml import load_hyperpyyaml
from torch.utils.data import DataLoader

import speechbrain as sb
from speechbrain.dataio.dataloader import LoopedLoader
from speechbrain.utils.distributed import run_on_main
from speechbrain.utils.kmeans import fetch_kmeans_model, save_model, train

logger = logging.getLogger(__name__)


def dataio_prepare(hparams):
    """This function prepares the datasets to be used in the brain class.
    It also defines the data processing pipeline through user-defined functions.
    """
    data_folder = hparams["data_folder"]

    train_data = sb.dataio.dataset.DynamicItemDataset.from_csv(
        csv_path=hparams["train_csv"],
        replacements={"data_root": data_folder},
    )

    if hparams["sorting"] == "ascending":
        # we sort training data to speed up training and get better results.
        train_data = train_data.filtered_sorted(sort_key="duration")
        # when sorting do not shuffle in dataloader ! otherwise is pointless
        hparams["train_dataloader_opts"]["shuffle"] = False

    elif hparams["sorting"] == "descending":
        train_data = train_data.filtered_sorted(
            sort_key="duration", reverse=True
        )
        # when sorting do not shuffle in dataloader ! otherwise is pointless
        hparams["train_dataloader_opts"]["shuffle"] = False

    elif hparams["sorting"] == "random":
        pass

    else:
        raise NotImplementedError(
            "sorting must be random, ascending or descending"
        )

    datasets = [train_data]

    # 2. Define audio pipeline:
    @sb.utils.data_pipeline.takes("wav")
    @sb.utils.data_pipeline.provides("sig")
    def audio_pipeline(wav):
        sig = sb.dataio.dataio.read_audio(wav)
        info = torchaudio.info(wav)
        resampled = torchaudio.transforms.Resample(
            info.sample_rate,
            hparams["sample_rate"],
        )(sig)
        return resampled

    sb.dataio.dataset.add_dynamic_item(datasets, audio_pipeline)

    # 4. Set output:
    sb.dataio.dataset.set_output_keys(
        datasets,
        ["id", "sig"],
    )
    return train_data


if __name__ == "__main__":
    # Load hyperparameters file with command-line overrides
    hparams_file, run_opts, overrides = sb.parse_arguments(sys.argv[1:])

    with open(hparams_file) as fin:
        hparams = load_hyperpyyaml(fin, overrides)

    # Create experiment directory
    sb.create_experiment_directory(
        experiment_directory=hparams["output_folder"],
        hyperparams_to_save=hparams_file,
        overrides=overrides,
    )

    # Dataset prep (parsing Librispeech)
    from librispeech_prepare import prepare_librispeech  # noqa

    # multi-gpu (ddp) save data preparation
    run_on_main(
        prepare_librispeech,
        kwargs={
            "data_folder": hparams["data_folder"],
            "tr_splits": hparams["train_splits"],
            "dev_splits": hparams["dev_splits"],
            "te_splits": hparams["test_splits"],
            "save_folder": hparams["output_folder"],
            "merge_lst": hparams["train_splits"],
            "merge_name": "train.csv",
            "skip_prep": hparams["skip_prep"],
        },
    )

    # Load SSL model
    hparams["ssl_model"] = hparams["ssl_model"].to(run_opts["device"])

    # Make training Dataloader
    train_set = dataio_prepare(hparams)
    if not (
        isinstance(train_set, DataLoader) or isinstance(train_set, LoopedLoader)
    ):
        train_set = sb.dataio.dataloader.make_dataloader(
            train_set, **hparams["train_dataloader_opts"]
        )

    # Load pretrained KMeans model if it exists. Otherwise,  create new one.
    checkpoint_path = os.path.join(
        hparams["save_folder"], f"kmeans_{hparams['num_clusters']}.pt"
    )
    kmeans_model = fetch_kmeans_model(
        n_clusters=hparams["num_clusters"],
        init=hparams["init"],
        max_iter=hparams["max_iter"],
        batch_size=hparams["batch_size"],
        tol=hparams["tol"],
        max_no_improvement=hparams["max_no_improvement"],
        n_init=hparams["n_init"],
        reassignment_ratio=hparams["reassignment_ratio"],
        random_state=hparams["seed"],
        checkpoint_path=checkpoint_path,
    )

    # Train and save Kmeans model
    train(
        kmeans_model,
        train_set,
        hparams["ssl_model"],
        hparams["ssl_layer_num"],
        kmeans_batch_size=hparams["kmeans_batch_size"],
        device=run_opts["device"],
    )

    logger.info(f"Saving kmeans model at {checkpoint_path}.")
    save_model(kmeans_model, checkpoint_path)
