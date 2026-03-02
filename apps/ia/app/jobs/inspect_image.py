#!/usr/bin/env python3
"""
Script para inspecionar a imagem e ver o que o Gemini consegue ler.
"""
import asyncio
import base64
import os
import sys

import google.generativeai as genai

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
IMAGE_PATH = "/tmp/contrato_debug.jpeg"


async def main():
    if not os.path.exists(IMAGE_PATH):
        print(f"ERRO: Imagem {IMAGE_PATH} não encontrada")
        print("Execute o script reread_missing_contract.py primeiro")
        return

    with open(IMAGE_PATH, "rb") as f:
        image_bytes = f.read()

    print(f"Imagem: {IMAGE_PATH} ({len(image_bytes)} bytes)")
    print("=" * 80)

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = """Descreva esta imagem em detalhes. O que você vê?

Diga:
1. Que tipo de documento é este?
2. Quais palavras/textos você consegue ler (liste TODAS)?
3. A qualidade da imagem é boa o suficiente para extrair dados?
4. Se é um contrato, onde está o número do contrato?"""

    image_b64 = base64.b64encode(image_bytes).decode('utf-8')

    response = await model.generate_content_async([
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_b64
            }
        },
        prompt
    ])

    print("RESPOSTA DO GEMINI:")
    print("=" * 80)
    print(response.text)
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
