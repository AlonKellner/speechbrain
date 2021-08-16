"""
A convenience wrapper for word embeddings retrieved out of
HuggingFace transformers (e.g. BERTs)

Authors
* Artem Ploujnikov 2021
"""


import torch
import numpy as np


def _last_n_layers(count):
    return range(-count, 0)


class TransformerWordEmbeddings:
    MSG_WORD = "'word' should be either a word or the index of a ord"

    """
    A wrapper to retrieve word embeddings out of a pretrained Transformer model from HuggingFace Transformers (e.g. BERT)

    Arguments
    ---------
    model: str|nn.Module
        the underlying model instance or the name of the model
        to download

    tokenizer: str|transformers.tokenization_utils_base.PreTrainedTokenizerBase
        a pretrained tokenizer - or the identifier to retrieve
        one from HuggingFace

    layers: int|list
        a list of layer indexes from which to construct an embedding or the number of layers

    device:
        a torch device identifier. If provided, the model
        will be transferred onto that device

    """
    DEFAULT_LAYERS = 4

    def __init__(self, model, tokenizer=None, layers=None, device=None):
        if not layers:
            layers = self.DEFAULT_LAYERS
        layers = _last_n_layers(layers) if isinstance(layers, int) else layers
        self.layers = list(layers)

        if isinstance(model, str):
            if tokenizer is None:
                tokenizer = model
            model = _get_model(model)
            if isinstance(tokenizer, str):
                tokenizer = _get_tokenizer(tokenizer)
        elif isinstance(tokenizer, None):
            raise ValueError(self.MSG_)

        self.model = model
        self.tokenizer = tokenizer
        if device is not None:
            self.device = device
            self.model = self.model.to(device)
        else:
            self.device = self.model.device

    def embedding(self, sentence, word):
        """Retrieves a word embedding for the specified word within
        a given sentence

        Arguments
        ---------
        sentence: str
            a sentence
        word: str|int
            a word or a word's index within the sentence. If a word
            is given, and it is encountered multiple times in a
            sentence, the first occurrence is used

        Returns
        -------
        emb: torch.Tensor
            the word embedding
        """
        encoded = self.tokenizer.encode_plus(sentence, return_tensors="pt")

        with torch.no_grad():
            output = self.model(**encoded)

        if isinstance(word, str):
            idx = self._get_word_idx(sentence, word)
        elif isinstance(word, int):
            idx = word
        else:
            raise ValueError(self.MSG_WORD)

        states = torch.stack(output.hidden_states)
        word_embedding = self._get_word_vector(encoded, states, idx).mean(dim=0)
        return word_embedding

    def embeddings(self, sentence):
        """
        Returns the model embeddings for all words
        in a sentence

        Arguments
        ---------
        sentence: str
            a sentence

        Returns
        -------
        emb: torch.Tensor
            a tensor of dimension
        """
        encoded = self.tokenizer.encode_plus(sentence, return_tensors="pt")

        with torch.no_grad():
            output = self.model(**encoded)

        token_ids_word = torch.tensor(
            [
                idx
                for idx, word_id in enumerate(encoded.word_ids())
                if word_id is not None
            ],
            device=self.device,
        )
        states = torch.stack(output.hidden_states)
        return self._get_hidden_states(states, token_ids_word)

    def batch_embeddings(self, sentences):
        """Returns embeddings for a collection of sentences

        Arguments
        ---------
        sentences: List[str]
            a list of strings corresponding to a batch of
            sentences

        Returns
        -------
        emb: torch.Tensor
            a (B x W x E) tensor
            B - the batch dimensions (samples)
            W - the word dimension
            E - the embedding dimension
        """
        encoded = self.tokenizer.batch_encode_plus(
            sentences, padding=True, return_tensors="pt"
        )

        with torch.no_grad():
            output = self.model(**encoded)

        states = torch.stack(output.hidden_states)
        return self._get_hidden_states(states)

    def _get_word_idx(self, sent, word):
        return sent.split(" ").index(word)

    def _get_hidden_states(self, states, token_ids_word=None):
        output = states[self.layers].sum(0).squeeze()
        if token_ids_word is not None:
            output = output[token_ids_word]
        else:
            output = output[:, 1:-1, :]
        return output

    def _get_word_vector(self, encoded, states, idx):
        token_ids_word = torch.from_numpy(
            np.where(np.array(encoded.word_ids()) == idx)[0]
        ).to(self.device)
        return self._get_hidden_states(states, token_ids_word)

    def to(self, device):
        self.device = device
        self.model = self.model.to(device)
        return self


class MissingTransformersError(Exception):
    MESSAGE = "This module requires HuggingFace Transformers"

    def __init__(self):
        super().__init__(self.MESSAGE)


def _get_model(identifier):
    """Tries to retrieve a pretrained model from Huggingface"""
    try:
        from transformers import AutoModel  # noqa

        return AutoModel.from_pretrained(identifier, output_hidden_states=True)
    except ImportError:
        raise MissingTransformersError()


def _get_tokenizer(identifier):
    """Tries to retreive a pretrained tokenizer from HuggingFace"""
    try:
        from transformers import AutoTokenizer  # noqa

        return AutoTokenizer.from_pretrained(identifier)
    except ImportError:
        raise MissingTransformersError()


