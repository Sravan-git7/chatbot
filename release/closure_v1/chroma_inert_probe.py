"""Offline inert provider hooks only; never loads model code or connects to a server."""
import json,tempfile
from pathlib import Path
import chromadb
from chromadb.config import Settings
from chromadb.api.types import EmbeddingFunction
from chromadb.utils.embedding_functions import known_embedding_functions
from chromadb.api.collection_configuration import load_create_collection_configuration_from_json
calls=[]
class Inert(EmbeddingFunction):
    def __init__(self):pass
    def __call__(self,input):return [[1.0,0.0] for _ in input]
    @staticmethod
    def name():return 'closure_inert_probe'
    def get_config(self):return {'trust_remote_code':True,'model_name':'inert-no-network-no-model'}
    @staticmethod
    def build_from_config(config):calls.append(dict(config));return Inert()
    @staticmethod
    def validate_config(config):pass
known_embedding_functions[Inert.name()]=Inert
payload={'embedding_function':{'type':'known','name':Inert.name(),'config':Inert().get_config()}}
load_create_collection_configuration_from_json(payload)
report={'scope':'inert registered constructor, not remote-code exploit; no downloads/network/model; package 1.5.9','create_config_deserialization_calls':list(calls)}
with tempfile.TemporaryDirectory(prefix='sura-inert-') as td:
    c=chromadb.PersistentClient(path=td,settings=Settings(anonymized_telemetry=False))
    col=c.create_collection('closure_probe',configuration={'embedding_function':Inert()},embedding_function=None)
    col.add(ids=['fixture'],embeddings=[[1.,0.]])
    calls.clear();got=c.get_collection('closure_probe');report['get_collection_provider_calls']=list(calls)
    calls.clear();got.get(limit=1,include=['embeddings']);report['get_explicit_vectors_provider_calls']=list(calls)
    calls.clear();got.query(query_embeddings=[[1.,0.]],n_results=1);report['query_explicit_vectors_provider_calls']=list(calls)
    calls.clear();_=got.configuration;report['configuration_property_provider_calls']=list(calls)
    c.close()
known_embedding_functions.pop(Inert.name())
Path(__file__).with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
