FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt \
 && python -m spacy download fr_core_news_md \
 && python -m spacy download en_core_web_md \
 && python -m spacy download de_core_news_md \
 && python -m spacy download es_core_news_md \
 && python -m spacy download it_core_news_md \
 && python -m spacy download nl_core_news_md \
 && python -m spacy download pt_core_news_md \
 && python -m spacy download xx_ent_wiki_sm \
 && python -m playwright install chromium --with-deps

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
