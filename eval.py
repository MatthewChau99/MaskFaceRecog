"""
Evaluate the model. (For validation and testing)
"""
import argparse
import logging
import os

import numpy as np
import torch
from torch.nn.functional import normalize
from tqdm import tqdm

import dataloader
import model
import utils
from metrics import evaluate_metrics

parser = argparse.ArgumentParser()

parser.add_argument("--data_dir", default="data/val",
                    help="Directory containing the dataset")
parser.add_argument("--model_dir", default="result/base_model",
                    help="Directory saving the model and log files")
parser.add_argument("--pretrained", default="last",
                    help="Optional, filename in --model_dir containing weights to load")  # 'best' or 'last'


def generate_embeddings(net: model.FocusFace, target: torch.Tensor, data: torch.Tensor):
    """
    Generate embeddings for a batch of input masked/unmasked data
    :param net: the FocusFace model
    :param target: the identity that the data belongs to
    :param data: the image data

    :return the embedding of the data image
    """
    # Normalization
    img = (((data / 255) - 0.5) / 0.5)

    # Getting the embedding
    embed = net(img, target, inference=True)[1]

    return embed


def embedding_dist(embed1: np.ndarray, embed2: np.ndarray) -> torch.Tensor:
    """
    Calculates the similarity score between the all pairs of embeddings in each batch using the formula
    similarity = 1 - (1/2) norm(embed1, embed2)

    :param embed1: the first batch of embeddings
    :param embed2: the second batch of embeddings

    :return similarity scores between each pair of embeddings in embed1 and embed2
    """
    embeds = []

    for i in range(embed1.shape[0]):
        sim = 1 - torch.cdist(embed1[i].reshape(1, -1),
                              embed2[i].reshape(1, -1)).detach().cpu().numpy()[0][0] / 2
        embeds.append(sim)

    return embeds


def evaluate(model_dir: str, net: model.FocusFace, data_loader: torch.utils.data.DataLoader, device: torch.device) -> dict:
    """
    Generate genuine and imposter embedding scores and use thøose scores to generate evaluate metrics.
    Current evaluation metrics: EER, AUC, g-mean, i-mean, FMR100, FMR10

    :param model_dir: the directory of the trained model
    :param net: the FocusFace model
    :param data_loader: the dataloader (could either be train or val loader)
    :param device: 'cuda' if cuda is available else 'cpu'

    :return a dictionary consisting of evaluation metrics and values
    """

    with torch.no_grad():
        gscores, iscores = [], []

        for i, (gen, imp) in enumerate(tqdm(data_loader), 0):
            # Retrieving data from dataloader
            gen_target, gen_masked, gen_unmasked = gen['target'][0].to(
                device), gen['masked'].to(device), gen['unmasked'].to(device)
            imp_target, imp_masked, imp_unmasked = imp['target'][1].to(
                device), imp['masked'].to(device), imp['unmasked'].to(device)

            # Generating the embeddings for genuine and imposter datasets
            gen_emb1 = generate_embeddings(net, gen_target, gen_masked)
            gen_emb2 = generate_embeddings(net, gen_target, gen_unmasked)
            gen_emb1, gen_emb2 = normalize(gen_emb1), normalize(gen_emb2)

            imp_emb1 = generate_embeddings(net, imp_target, imp_masked)
            imp_emb2 = generate_embeddings(net, imp_target, imp_unmasked)
            imp_emb1, imp_emb2 = normalize(imp_emb1), normalize(imp_emb2)

            # Generating gscores and iscores
            g_dist = embedding_dist(gen_emb1, gen_emb2)
            i_dist = embedding_dist(imp_emb1, imp_emb2)

            gscores.extend(g_dist)
            iscores.extend(i_dist)

    return evaluate_metrics(model_dir, gscores, iscores, clf_name='A', print_results=True)


if __name__ == '__main__':
    """
        Evaluate the model on the test set
    """
    args = parser.parse_args()

    torch.manual_seed(230)
    if torch.cuda.is_available():
        device = torch.device("cuda")
        torch.cuda.manual_seed(230)
    else:
        device = torch.device("cpu")

    utils.set_logger(os.path.join(args.model_dir, "test.log"))
    batch_size = 64
    workers = 2
    logging.info("Loading the datasets ...")
    _, test_loader = dataloader.create_dataloader(
        args.data_dir, batch_size, workers)
    logging.info("- Done.")

    identities = 601
    net = model.FocusFace(identities).to(device)
    
    # Load weights from the saved file
    pretrain_path = os.path.join(args.model_dir, args.pretrained + ".pth.tar")
    logging.info("Loading parameters from {}".format(pretrain_path))
    utils.load_checkpoint(pretrain_path, net)

    logging.info("Start evaluation ...")
    test_metrics = evaluate(args.model_dir, net, test_loader, device)
    save_path = os.path.join(
        args.model_dir, "test_metrics_{}.json".format(args.pretrained))
    utils.save_dict_to_json(test_metrics, save_path)
