import logging
import torch
import uvicorn
from fastapi import FastAPI, Request
from energonai.engine import InferenceEngine
from fastapi.middleware.cors import CORSMiddleware
from transformers import GPT2Tokenizer
from pydantic import BaseModel, Field
from typing import Optional
from executor import Executor


class GenerationTaskReq(BaseModel):
    max_tokens: int = Field(gt=0)
    prompt: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, gt=0)
    top_p: Optional[float] = Field(default=None, gt=0.0, lt=1.0)
    temperature: Optional[float] = Field(default=None, gt=0.0, lt=1.0)


app = FastAPI()


@app.post('/generation')
async def generate(data: GenerationTaskReq, request: Request):
    logger.info(f'{request.client.host}:{request.client.port} - "{request.method} {request.url.path}" - {data}')
    handle = executor.submit(data.prompt, data.max_tokens, data.top_k, data.top_p, data.temperature)
    output = await executor.wait(handle)
    return {'text': output}


@app.on_event("shutdown")
async def shutdown():
    executor.teardown()
    engine.clear()
    server.should_exit = True
    server.force_exit = True
    await server.shutdown()


def launch_engine(model_class,
                  model_type,
                  max_batch_size: int = 1,
                  tp_init_size: int = -1,
                  pp_init_size: int = -1,
                  host: str = "localhost",
                  port: int = 29500,
                  dtype=torch.float,
                  checkpoint: str = None,
                  tokenizer_path: str = None,
                  server_host="localhost",
                  server_port=8005,
                  log_level="info",
                  allow_cors: bool = False
                  ):
    if allow_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['*'],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    global logger
    logger = logging.getLogger(__name__)
    # only for the generation task
    global tokenizer
    if(tokenizer_path):
        tokenizer = GPT2Tokenizer.from_pretrained(tokenizer_path, padding_side='left')

    if checkpoint:
        model_config = {'dtype': dtype, 'checkpoint': checkpoint}
    else:
        model_config = {'dtype': dtype}

    global engine
    engine = InferenceEngine(model_class,
                             model_config,
                             model_type,
                             max_batch_size=max_batch_size,
                             tp_init_size=tp_init_size,
                             pp_init_size=pp_init_size,
                             host=host,
                             port=port,
                             dtype=dtype)
    global executor
    executor = Executor(engine, tokenizer, max_batch_size=16)
    executor.start()

    global server
    config = uvicorn.Config(app, host=server_host, port=server_port, log_level=log_level)
    server = uvicorn.Server(config=config)
    server.run()