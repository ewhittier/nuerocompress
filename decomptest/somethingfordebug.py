'''Example script to generate text from Nietzsche's writings.
At least 20 epochs are required before the generated text
starts sounding coherent.
It is recommended to run this script on GPU, as recurrent
networks are quite computationally intensive.
If you try this script on new data, make sure your corpus
has at least ~100k characters. ~1M is better.
'''
from __future__ import print_function
import keras.models 
from keras.layers import Dense, Activation
from keras.layers import LSTM
from keras.optimizers import RMSprop, Adagrad, Adadelta, Adam 
from keras.utils.data_utils import get_file
import numpy as np
import random
import sys
import json
import bz2
import arithmeticcoding


np.random.seed(7)

# path = get_file('nietzsche.txt', origin='https://s3.amazonaws.com/text-datasets/nietzsche.txt')
# text = open(path).read().lower()
# text = "abcdefghijklmnopqrstuvwxyz" * 10

text = ''

with open('poetry_ascii.txt', 'r') as f:
  text = f.read()

print('corpus length:', len(text))

chars = sorted(list(set(text)))

AE_SIZE = 257
MAGIC_EOF=AE_SIZE-1
HIDDEN_SIZE=512
NUM_LAYERS=2
VOCAB_SIZE=len(chars)


print('total chars:', VOCAB_SIZE)

char_indices = dict((c, i) for i, c in enumerate(chars))
#char_indices['~'] = VOCAB_SIZE

indices_char = dict((i, c) for i, c in enumerate(chars))
#indices_char[VOCAB_SIZE] = '~'

#JUNK = '~'
#junk_count = 0


# cut the text in semi-redundant sequences of maxlen characters
maxlen = 30
step = 1
sentences = []
next_chars = []
for i in range(0, len(text) - maxlen, step):
    sentences.append(text[i: i + maxlen])
    next_chars.append(text[i + maxlen])
print('nb sequences:', len(sentences))

print('Vectorization...')
X = np.zeros((len(sentences), maxlen, VOCAB_SIZE+1), dtype=np.bool)
y = np.zeros((len(sentences), VOCAB_SIZE+1), dtype=np.bool)
for i, sentence in enumerate(sentences):
    for t, char in enumerate(sentence):
        X[i, t, char_indices[char]] = 1
    y[i, char_indices[next_chars[i]]] = 1

# build the model: a single LSTM
print('Build model...')

model = keras.models.Sequential()

if NUM_LAYERS == 1:
    model.add(LSTM(HIDDEN_SIZE, input_shape=(maxlen, VOCAB_SIZE+1), return_sequences = False))
else:
    model.add(LSTM(HIDDEN_SIZE, input_shape=(maxlen, VOCAB_SIZE+1), return_sequences = True))
    for i in range(NUM_LAYERS-2):
        model.add(LSTM(HIDDEN_SIZE, return_sequences = True))
    model.add(LSTM(HIDDEN_SIZE))

model.add(Dense(VOCAB_SIZE+1))
model.add(Activation('softmax'))

optimizer = Adam()

model.compile(loss='categorical_crossentropy', optimizer=optimizer)

'''def sample(preds, temperature=1.0):
    # helper function to sample an index from a probability array
    #print(len(preds))
    preds = np.asarray(preds).astype('float64')
    #print(len(preds))
    #print(type(temperature))
    preds = np.log(preds) / temperature
    exp_preds = np.exp(preds)
    preds = exp_preds / np.sum(exp_preds)
    probas = np.random.multinomial(1, preds, 1)
    return np.argmax(probas)
'''
def sample_det(preds, temperature=1.0):
    # helper function to sample an index from a probability array deterministically
    preds = np.asarray(preds).astype('float64')
    preds = np.log(preds) / temperature
    exp_preds = np.exp(preds)
    probs = exp_preds / np.sum(exp_preds)
    return np.argmax(probs)

def predict(sentence, model, indices_char, diversity=0.1):
    
    x = np.zeros((1, maxlen, VOCAB_SIZE+1))
    for t, char in enumerate(sentence):
        try:
            #print('char',char)
            x[0, t, char_indices[char]] = 1.
        except KeyError as e:
            print('I got a KeyError - reason ',str(e))
            print('replacing with junk character')
            x[0, t, char_indices['a']] = 1.
            pass

    preds = model.predict(x, verbose=0)[0]
    next_index = sample_det(preds, diversity)
    next_char = indices_char[next_index]
    return next_char

def comparess(file1, model, indices_char):
    #this is painfully slow
    #if at all possible it should be revised so that it can mostly be run on the gpu
    #by painfully slow i mean on the order of .02 seconds per character guess. 
    #ie ~16 minutes for a 50k character file.

    f1 = open(file1, 'r').read()
    data_size = len(f1)
    i = 0
    #output = [0, f1[0]]

    bitout = arithmeticcoding.BitOutputStream(open(file1 + '.comp', "wb"))
    initfreqs = arithmeticcoding.FlatFrequencyTable(AE_SIZE)
    freqs = arithmeticcoding.SimpleFrequencyTable(initfreqs)
    enc = arithmeticcoding.ArithmeticEncoder(bitout)
    guesses_right = 0
    gss = ''

    while i < data_size:
        current = ord(f1[i])
        if i < maxlen:
            enc.write(freqs, 0)  # Always 'guessing' zero correctly before maxlen
            freqs.increment(0)
            enc.write(freqs, current)
            freqs.increment(current)
        else:
            guess = predict(f1[(i-maxlen):i] , model, indices_char)
            if(f1[i] == guess and guesses_right < 255):
                guesses_right += 1
                print("Guessed",f1[i],"correctly")
            else:
                enc.write(freqs, guesses_right)
                print("Wrong guess. Outputing",guesses_right,"correct guesses")
                freqs.increment(guesses_right)
                print(i, "Outputing char", current)
                enc.write(freqs, current)
                freqs.increment(current)
                guesses_right = 0

        if (i % 100 == 0): print("i:", i)
        i += 1

    if guesses_right > 0:
        enc.write(freqs, guesses_right)
    enc.write(freqs, MAGIC_EOF)
    print("out eof sanity check")
    enc.finish()
    bitout.close()
    return None

def decomparess(inputfile, outfile, model):
    bitin = arithmeticcoding.BitInputStream(open(inputfile, "rb"))
    initfreqs = arithmeticcoding.FlatFrequencyTable(AE_SIZE)
    freqs = arithmeticcoding.SimpleFrequencyTable(initfreqs)
    dec = arithmeticcoding.ArithmeticDecoder(bitin)
    prev_chars = []
    i = 0

    with open(outfile, "w") as out:
        
        while(True):

            guesses = dec.read(freqs)
            freqs.increment(guesses)
            if guesses == MAGIC_EOF:
                break

            print('guesses',guesses)
            
            print(prev_chars)
            for _ in range(guesses):
                 print(prev_chars)
                 char = predict(prev_chars, model, indices_char)
                 print('lit for guess',char)
                 prev_chars.append(char)
                 if len(prev_chars) > maxlen:
                    prev_chars.pop(0)
                 out.write(char)

            print("i",i)
            literal = dec.read(freqs)
            if literal == MAGIC_EOF:
                break
            print('lit',chr(literal))
            out.write(chr(literal))
            freqs.increment(literal)
            prev_chars.append(chr(literal))
            if len(prev_chars) > maxlen:
                 prev_chars.pop(0)
            i = i + 1

        bitin.close()

def train(model = model, bsize = HIDDEN_SIZE, epochs = 1, iters = 1):
    for iteration in range(iters):
        print()
        print('-' * 50)
        print('Iteration', iteration)
        model.fit(X, y,
              batch_size= bsize,
              epochs=epochs)
'''
def save(model_path = 'first(128,40)/model.json', weights_path = 'first(128,40)/weights.h5'):
    model_json = model.to_json()
    with open(model_path, "w") as json_file:
        json_file.write(model_json)
    # serialize weights to HDF5
    model.save_weights(weights_path)
    print("Saved model to disk")
    
def load(model_path = 'first(128,40)/model.json', weights_path = 'first(128,40)/weights.h5'):
    json_file = open(model_path, 'r')
    loaded_model_json = json_file.read()
    json_file.close()
    loaded_model = model_from_json(loaded_model_json)
    # load weights into new model
    loaded_model.load_weights(weights_path)

    print("Loaded model from disk")
    return loaded_model
'''
'''def guess(char):
    seed = [char_to_int[char]]
    x = numpy.reshape(seed, (1, len(seed), 1))
    x = x / float(vocab_size)
    prediction = model.predict(x, verbose=0)
    index = numpy.argmax(prediction)
    return int_to_char[index]
'''


#print(model.get_weights())

#model = load('saves/1/model.json', 'saves/1/weights.h5')

# train the model, output generated text after each iteration
'''for iteration in range(1):
    print()
    print('-' * 50)
    print('Iteration', iteration)
    model.fit(X, y,
              batch_size=128,
              epochs=10)
'''

'''with open('model.json') as f:
    jstr = json.load(f)

model = 
'''


'''
comped = comparess('alice.txt', model, indices_char)
outstr = "".join(comped)
utstr = "".join(comped)


#bcomped = bz2.compress(comped, 9)


#import json
#jstr =json.dumps(comped)
with bz.open('comped.txt',mode = 'w', 9) as f:
    f.write(comped)
print(comped)

decomped = decomparess(comped, model)

print(decomped)

with open('decomped.txt','w') as f:
    f.write(decomped)  
'''

train(epochs=50)
model.save('asciipoems2layers51.h5')
comparess('poetry_ascii.txt', model, indices_char)
decomparess('poetry_ascii.txt.comp', 'poetry_ascii.txt.decomp', model)

