# Exemplos de Uso — HAR Content Extractor

## 1. E-commerce: Extrair catálogo de produtos

```bash
# 1. Abra o site de e-commerce no Chrome
# 2. F12 → Network → navegue por categorias e produtos
# 3. Exporte o HAR (botão direito → Save all as HAR)

python main.py \
  --har mercadolivre.har \
  --goal "extrair todos os produtos com título, preço, preço original, desconto, link do produto, link da imagem principal, vendedor e quantidade vendida" \
  --format excel \
  --output ./dados-ml
```

**Resultado**: Excel com colunas formatadas contendo o catálogo completo.

---

## 2. Blog / Portal de Notícias

```bash
python main.py \
  --har portal-noticias.har \
  --goal "extrair todos os artigos com título, autor, data de publicação, resumo, link e imagem de capa" \
  --format csv \
  --output ./artigos
```

---

## 3. Galeria de Imagens em Alta Resolução

```bash
python main.py \
  --har galeria.har \
  --goal "extrair todas as imagens em resolução máxima disponível" \
  --format json \
  --download-assets \
  --output ./imagens-hd
```

**Resultado**: JSON com metadados + pasta `downloads/` com todas as imagens baixadas.

---

## 4. Apenas Análise (sem extração)

Útil para entender a arquitetura de um site antes de decidir o que extrair:

```bash
python main.py \
  --har site-qualquer.har \
  --analyze-only \
  --output ./analise
```

**Resultado**: Arquivo `site_analysis.md` com breakdown completo da arquitetura.

---

## 5. Site com Autenticação (cookies/tokens)

Se o site precisa de login, o HAR captura os cookies da sessão automaticamente:

```bash
# 1. Faça login no site
# 2. Navegue pelas páginas que quer extrair
# 3. Exporte o HAR (os cookies estarão incluídos)

python main.py \
  --har site-logado.har \
  --goal "extrair meus pedidos com número, data, status, valor e itens" \
  --replay-headers \
  --format excel
```

O `--replay-headers` reutiliza os cookies e tokens capturados no HAR.

---

## 6. API com Paginação

Para sites que carregam dados via API com paginação:

```bash
python main.py \
  --har loja-api.har \
  --goal "extrair todos os produtos de todas as páginas" \
  --max-pages 100 \
  --format json
```

---

## 7. Marketplace (Shopee, Amazon, etc.)

```bash
python main.py \
  --har shopee.har \
  --goal "extrair listagem com nome do produto, preço, avaliação, quantidade de avaliações, vendedor e link" \
  --format excel \
  --concurrency 2 \
  --output ./shopee-dados
```

> **Nota**: Use `--concurrency 2` para marketplaces grandes para evitar rate limiting.

---

## Dicas

1. **Quanto mais páginas você navegar antes de exportar o HAR, melhor**. O parser entende padrões de paginação e APIs quando vê múltiplas requisições similares.

2. **Para sites SPA** (React, Vue, Angular), os dados geralmente vêm de APIs JSON. O parser detecta isso automaticamente.

3. **Para sites SSR tradicionais**, o parser analisa o HTML mas prioriza APIs se encontrar alguma.

4. **Se a extração falhar**, rode `--analyze-only` primeiro para entender a estrutura do site e refinar seu `--goal`.
