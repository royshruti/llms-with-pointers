import os
from loguru import logger
import torch
import wandb

from datasets import Dataset

from src.config import ScriptArguments
from src.batcher import get_training_batch_generator
from src.model import create_and_prepare_model

from trl import SFTTrainer
from trl import SFTConfig
from trl import setup_chat_format

from transformers import PreTrainedModel
from transformers import BitsAndBytesConfig
from transformers import pipeline
from transformers import TrainingArguments

from peft.auto import AutoPeftModelForCausalLM
from peft.tuners.lora.config import LoraConfig
from peft.peft_model import PeftModel
from peft.utils.other import prepare_model_for_kbit_training
from peft.mapping import get_peft_model


def train(params: ScriptArguments):

    training_arguments = TrainingArguments(
        output_dir=params.output_dir,
        per_device_train_batch_size=params.per_device_train_batch_size,
        per_device_eval_batch_size=params.per_device_eval_batch_size,
        optim=params.optim,
        save_steps=params.save_steps,
        logging_steps=params.logging_steps,
        learning_rate=params.learning_rate,
        fp16=params.fp16,
        bf16=params.bf16,
        max_grad_norm=params.max_grad_norm,
        max_steps=params.max_steps,
        warmup_steps=params.warmup_steps,
        group_by_length=params.group_by_length,
        lr_scheduler_type=params.lr_scheduler_type,
        report_to=params.reports_to,
    )

    logger.info("Creating and Preparing Model For Training.")
    model, peft_config, tokenizer = create_and_prepare_model(params)
    logger.success("Model Successfully Created For Training.")

    logger.info("Creating Dataset Generator.")
    train_gen = Dataset.from_generator(get_training_batch_generator(tokenizer, params))
    logger.success("Dataset Generator Successfully Created.")

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_gen,
        peft_config=peft_config,
        dataset_text_field="text",
        max_seq_length=params.max_seq_length,
        tokenizer=tokenizer,
        args=training_arguments,
        packing=params.packing,
    )

    trainer.train()

    if params.merge_and_push:
        output_dir = os.path.join(params.output_dir, "final_checkpoints")
        trainer.model.save_pretrained(output_dir)

        # Free memory from mergin weights
        del model
        torch.cuda.empty_cache()

        model = AutoPeftModelForCausalLM.from_pretrained(
            output_dir,
            low_cpu_mem_usage=True,
            device_map="auto",
            torch_dtype=torch.bfloat16,
        )
        model: PreTrainedModel = model.merge_and_unload()

        output_merged_dir = os.path.join(params.output_dir, "final_merged_checkpoints")
        model.save_pretrained(output_merged_dir, safe_serialization=True)
