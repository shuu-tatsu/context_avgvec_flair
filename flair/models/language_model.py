from pathlib import Path

import torch.nn as nn
import torch
import math
from typing import Union, Tuple
from typing import List

from torch.optim import Optimizer

import flair
from flair.data import Dictionary


class LanguageModel(nn.Module):
    """Container module with an encoder, a recurrent module, and a decoder."""

    def __init__(self,
                 dictionary: Dictionary,
                 is_forward_lm: bool,
                 hidden_size: int,
                 nlayers: int,
                 embedding_size: int = 100,
                 nout=None,
                 dropout=0.1):

        super(LanguageModel, self).__init__()

        self.dictionary = dictionary
        self.is_forward_lm: bool = is_forward_lm

        self.dropout = dropout
        self.hidden_size = hidden_size
        self.embedding_size = embedding_size
        self.nlayers = nlayers

        self.drop = nn.Dropout(dropout)
        self.encoder = nn.Embedding(len(dictionary), embedding_size)

        '''
        if nlayers == 1:  #nlayersのデフォルトは1
            self.rnn = nn.LSTM(embedding_size, hidden_size, nlayers)
        else:
            self.rnn = nn.LSTM(embedding_size, hidden_size, nlayers, dropout=dropout)
        '''
        # fix start
        self.rnn = nn.LSTMCell(embedding_size, hidden_size)
        # fix end

        self.hidden = None

        self.nout = nout
        if nout is not None:
            self.proj = nn.Linear(hidden_size, nout)
            self.initialize(self.proj.weight)
            self.decoder = nn.Linear(nout, len(dictionary))
        else:
            self.proj = None
            self.decoder = nn.Linear(hidden_size, len(dictionary))

        self.init_weights()

        # auto-spawn on GPU if available
        self.to(flair.device)

    def init_weights(self):
        initrange = 0.1
        self.encoder.weight.detach().uniform_(-initrange, initrange)
        self.decoder.bias.detach().fill_(0)
        self.decoder.weight.detach().uniform_(-initrange, initrange)

    def set_hidden(self, hidden):
        self.hidden = hidden

    def forward(self, input, hidden, ordered_sequence_lengths=None):
        encoded = self.encoder(input)
        emb = self.drop(encoded)

        '''
        self.rnn.flatten_parameters()
        '''
        #emb: 文字数 * 1batchセンテンス数 * 1文字のembサイズ(100dim)
        #output: 文字数 * 1batchセンテンス数 * 1文字のembサイズ(2048dim)
        #hidden: 1dim * 1batchセンテンス数 * 2048dim
        '''
        output, hidden = self.rnn(emb, hidden)
        '''
        # fix start
        hx = hidden[0][0]
        cx = hidden[1][0]
        #output = []
        hx_list = [] #抽出のため, outputと同じ
        cx_list = [] #抽出のため
        for i in range(emb.size()[0]):
            hx, cx = self.rnn(emb[i], (hx, cx))
            hx_list.append(hx)
            cx_list.append(cx)
        output = torch.stack(hx_list, dim=0)
        hx_stacked = torch.stack(hx_list, dim=0)
        cx_stacked = torch.stack(cx_list, dim=0)
        # fix end

        if self.proj is not None:
            output = self.proj(output)

        output = self.drop(output)

        decoded = self.decoder(output.view(output.size(0) * output.size(1), output.size(2)))

        '''
        return decoded.view(output.size(0), output.size(1), decoded.size(1)), output, hidden
        '''
        # fix start
        return decoded.view(output.size(0), output.size(1), decoded.size(1)), output, hidden, hx_stacked, cx_stacked
        # fix end

    def init_hidden(self, bsz):
        weight = next(self.parameters()).detach()
        return (weight.new(self.nlayers, bsz, self.hidden_size).zero_().clone().detach(),
                weight.new(self.nlayers, bsz, self.hidden_size).zero_().clone().detach())

    def get_representation(self, strings: List[str], chars_per_chunk: int = 512):
        # cut up the input into chunks of max charlength = chunk_size
        longest = len(strings[0])
        chunks = []
        splice_begin = 0
        for splice_end in range(chars_per_chunk, longest, chars_per_chunk):
            chunks.append([text[splice_begin:splice_end] for text in strings])
            splice_begin = splice_end

        chunks.append([text[splice_begin:longest] for text in strings])
        hidden = self.init_hidden(len(chunks[0]))

        output_parts = []
        # fix start
        hx_parts = []
        cx_parts = []
        # fix end

        # push each chunk through the RNN language model
        for chunk in chunks:

            sequences_as_char_indices: List[List[int]] = []
            for string in chunk:
                char_indices = [self.dictionary.get_idx_for_item(char) for char in string]
                sequences_as_char_indices.append(char_indices)

            batch = torch.LongTensor(sequences_as_char_indices).transpose(0, 1)
            batch = batch.to(flair.device)
            '''
            prediction, rnn_output, hidden = self.forward(batch, hidden)
            '''
            # fix start
            prediction, rnn_output, hidden, hx_stacked, cx_stacked = self.forward(batch, hidden)
            '''
            prediction.size(): torch.Size([66, 32, 275])
            rnn_output.size(): torch.Size([66, 32, 2048])
            len(hidden): 2
            hidden[0].size(): torch.Size([1, 32, 2048])
            hx_stacked.size(): torch.Size([66, 32, 2048])
            '''
            # fix end

            rnn_output = rnn_output.detach()
            output_parts.append(rnn_output)

            # fix start
            hx_parts.append(hx_stacked)
            cx_parts.append(cx_stacked)
            # fix end

        # concatenate all chunks to make final output
        output = torch.cat(output_parts)
        hx_out = torch.cat(hx_parts)
        cx_out = torch.cat(cx_parts)

        '''
        return output
        '''
        # fix start
        return output, hx_out, cx_out
        # fix end

    def get_output(self, text: str):
        char_indices = [self.dictionary.get_idx_for_item(char) for char in text]
        input_vector = torch.LongTensor([char_indices]).transpose(0, 1)

        hidden = self.init_hidden(1)
        prediction, rnn_output, hidden = self.forward(input_vector, hidden)

        return self.repackage_hidden(hidden)

    def repackage_hidden(self, h):
        """Wraps hidden states in new Variables, to detach them from their history."""
        if type(h) == torch.Tensor:
            return h.clone().detach()
        else:
            return tuple(self.repackage_hidden(v) for v in h)

    def initialize(self, matrix):
        in_, out_ = matrix.size()
        stdv = math.sqrt(3. / (in_ + out_))
        matrix.detach().uniform_(-stdv, stdv)

    @classmethod
    def load_language_model(cls, model_file: Union[Path, str]):

        state = torch.load(str(model_file), map_location=flair.device)

        model = LanguageModel(state['dictionary'],
                              state['is_forward_lm'],
                              state['hidden_size'],
                              state['nlayers'],
                              state['embedding_size'],
                              state['nout'],
                              state['dropout'])
        state['state_dict']['rnn.weight_ih'] = state['state_dict'].pop('rnn.weight_ih_l0')
        state['state_dict']['rnn.weight_hh'] = state['state_dict'].pop('rnn.weight_hh_l0')
        state['state_dict']['rnn.bias_ih'] = state['state_dict'].pop('rnn.bias_ih_l0')
        state['state_dict']['rnn.bias_hh'] = state['state_dict'].pop('rnn.bias_hh_l0')
        model.load_state_dict(state['state_dict'])
        model.eval()
        model.to(flair.device)

        return model

    @classmethod
    def load_checkpoint(cls, model_file: Path):
        state = torch.load(str(model_file), map_location=flair.device)

        epoch = state['epoch'] if 'epoch' in state else None
        split = state['split'] if 'split' in state else None
        loss = state['loss'] if 'loss' in state else None
        optimizer_state_dict = state['optimizer_state_dict'] if 'optimizer_state_dict' in state else None

        model = LanguageModel(state['dictionary'],
                              state['is_forward_lm'],
                              state['hidden_size'],
                              state['nlayers'],
                              state['embedding_size'],
                              state['nout'],
                              state['dropout'])
        model.load_state_dict(state['state_dict'])
        model.eval()
        model.to(flair.device)

        return {'model': model, 'epoch': epoch, 'split': split, 'loss': loss,
                'optimizer_state_dict': optimizer_state_dict}

    def save_checkpoint(self, file: Path, optimizer: Optimizer, epoch: int, split: int, loss: float):
        model_state = {
            'state_dict': self.state_dict(),
            'dictionary': self.dictionary,
            'is_forward_lm': self.is_forward_lm,
            'hidden_size': self.hidden_size,
            'nlayers': self.nlayers,
            'embedding_size': self.embedding_size,
            'nout': self.nout,
            'dropout': self.dropout,
            'optimizer_state_dict': optimizer.state_dict(),
            'epoch': epoch,
            'split': split,
            'loss': loss
        }

        torch.save(model_state, str(file), pickle_protocol=4)

    def save(self, file: Path):
        model_state = {
            'state_dict': self.state_dict(),
            'dictionary': self.dictionary,
            'is_forward_lm': self.is_forward_lm,
            'hidden_size': self.hidden_size,
            'nlayers': self.nlayers,
            'embedding_size': self.embedding_size,
            'nout': self.nout,
            'dropout': self.dropout
        }

        torch.save(model_state, str(file), pickle_protocol=4)

    def generate_text(self, prefix: str = '\n', number_of_characters: int = 1000, temperature: float = 1.0,
                      break_on_suffix=None) -> Tuple[str, float]:

        if prefix == '':
            prefix = '\n'

        with torch.no_grad():
            characters = []

            idx2item = self.dictionary.idx2item

            # initial hidden state
            hidden = self.init_hidden(1)

            if len(prefix) > 1:

                char_tensors = []
                for character in prefix[:-1]:
                    char_tensors.append(
                        torch.tensor(self.dictionary.get_idx_for_item(character)).unsqueeze(0).unsqueeze(0))

                input = torch.cat(char_tensors)
                if torch.cuda.is_available():
                    input = input.cuda()

                prediction, _, hidden = self.forward(input, hidden)

            input = torch.tensor(self.dictionary.get_idx_for_item(prefix[-1])).unsqueeze(0).unsqueeze(0)

            log_prob = 0.

            for i in range(number_of_characters):

                if torch.cuda.is_available():
                    input = input.cuda()

                # get predicted weights
                prediction, _, hidden = self.forward(input, hidden)
                prediction = prediction.squeeze().detach()
                decoder_output = prediction

                # divide by temperature
                prediction = prediction.div(temperature)

                # to prevent overflow problem with small temperature values, substract largest value from all
                # this makes a vector in which the largest value is 0
                max = torch.max(prediction)
                prediction -= max

                # compute word weights with exponential function
                word_weights = prediction.exp().cpu()

                # try sampling multinomial distribution for next character
                try:
                    word_idx = torch.multinomial(word_weights, 1)[0]
                except:
                    word_idx = torch.tensor(0)

                # print(word_idx)
                prob = decoder_output[word_idx]
                log_prob += prob

                input = word_idx.detach().unsqueeze(0).unsqueeze(0)
                word = idx2item[word_idx].decode('UTF-8')
                characters.append(word)

                if break_on_suffix is not None:
                    if ''.join(characters).endswith(break_on_suffix):
                        break

            text = prefix + ''.join(characters)

            log_prob = log_prob.item()
            log_prob /= len(characters)

            if not self.is_forward_lm:
                text = text[::-1]

            return text, log_prob

    def calculate_perplexity(self, text: str) -> float:

        if not self.is_forward_lm:
            text = text[::-1]

        # input ids
        input = torch.tensor([self.dictionary.get_idx_for_item(char) for char in text[:-1]]).unsqueeze(1)
        input = input.to(flair.device)

        # push list of character IDs through model
        hidden = self.init_hidden(1)
        prediction, _, hidden = self.forward(input, hidden)

        # the target is always the next character
        targets = torch.tensor([self.dictionary.get_idx_for_item(char) for char in text[1:]])
        targets = targets.to(flair.device)

        # use cross entropy loss to compare output of forward pass with targets
        cross_entroy_loss = torch.nn.CrossEntropyLoss()
        loss = cross_entroy_loss(prediction.view(-1, len(self.dictionary)), targets).item()

        # exponentiate cross-entropy loss to calculate perplexity
        perplexity = math.exp(loss)

        return perplexity
