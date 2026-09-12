# HAR Content Extractor

Ferramenta de extração inteligente de conteúdo a partir de arquivos HAR (HTTP Archive).  
A IA analisa todas as requisições de rede capturadas, entende como o site funciona internamente e extrai exatamente o que você precisa.

---

## Como funciona

```
┌─────────────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│  Captura o HAR  │────▶│  Parser lê   │────▶│  IA analisa   │────▶│  Extrator  │
│  no navegador   │     │  requisições │     │  arquitetura  │     │  executa   │
└─────────────────┘     └──────────────┘     └───────────────┘     └────────────┘
                                                                         │
                                                                         ▼
                                                                   ┌────────────┐
                                                                   │  Excel /   │
                                                                   │  CSV/JSON  │
                                                                   └────────────┘
```

1. **Captura**: Você exporta um arquivo `.har` do navegador (DevTools → Network → Export HAR)
2. **Parsing**: O parser analisa todas as requisições, identifica CDNs, APIs, diretórios de imagem, padrões de paginação
3. **Análise IA**: A IA recebe o perfil estruturado do site e gera um plano de extração otimizado
4. **Extração**: O extrator executa as requisições seguindo o plano da IA, lidando com paginação automaticamente
5. **Exportação**: Dados exportados para Excel (.xlsx), CSV ou JSON

---

## Pré-requisitos

- Python 3.10+
- Uma chave de API de qualquer provedor compatível com OpenAI (OpenRouter, OpenAI, Google AI Studio, etc.)

## Instalação

```bash
cd har-content-extractor
pip install -r requirements.txt
cp .env.example .env
# Edite o .env com sua chave de API
```

---

## Como capturar um HAR

### Chrome / Edge
1. Abra o site alvo
2. `F12` → aba **Network**
3. Navegue pelo site normalmente (carregue as páginas que quer extrair)
4. Clique com botão direito na lista de requisições → **Save all as HAR with content**

### Firefox
1. Abra o site alvo
2. `F12` → aba **Network**
3. Navegue pelo site
4. Ícone de engrenagem → **Save All As HAR**

> **Dica**: Quanto mais páginas você navegar, mais o parser entende a estrutura do site. Para e-commerce, navegue por categorias, produtos e busca.

---

## Uso

### Extração completa (análise + extração + exportação)
```bash
python main.py --har site.har --goal "extrair todos os produtos com nome, preço, imagem e link" --format excel
```

### Extrair imagens em alta resolução
```bash
python main.py --har site.har --goal "extrair todas as imagens em alta resolução" --format json --download-assets
```

### Apenas analisar o site (sem extrair)
```bash
python main.py --har site.har --analyze-only
```

### Especificar diretório de saída
```bash
python main.py --har site.har --goal "extrair artigos do blog" --format csv --output ./dados
```

### Usar headers customizados do HAR
```bash
python main.py --har site.har --goal "extrair dados da API" --replay-headers
```

---

## Parâmetros

| Parâmetro | Descrição |
|-----------|-----------|
| `--har` | Caminho para o arquivo .har |
| `--goal` | O que você quer extrair (em linguagem natural) |
| `--format` | Formato de saída: `excel`, `csv`, `json` (padrão: `excel`) |
| `--output` | Diretório de saída (padrão: `./output`) |
| `--analyze-only` | Apenas mostrar análise do site, sem extrair |
| `--download-assets` | Baixar imagens/arquivos referenciados |
| `--replay-headers` | Usar headers capturados no HAR (cookies, auth) |
| `--max-pages` | Máximo de páginas a percorrer (padrão: 50) |
| `--concurrency` | Requisições simultâneas (padrão: 3) |
| `--verbose` | Log detalhado |

---

## Estrutura do Projeto

```
har-content-extractor/
├── main.py              # CLI entry point
├── har_parser.py         # Parser de arquivos HAR
├── ai_analyzer.py        # Análise via IA (OpenAI-compatible)
├── extractor.py          # Engine de extração HTTP
├── exporter.py           # Exportação Excel/CSV/JSON
├── prompts/
│   ├── base_prompt.txt           # Prompt base para análise de site
│   └── extraction_prompt.txt     # Prompt para plano de extração
├── examples/
│   └── example_usage.md          # Exemplos de uso
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Cenários de Uso

- **E-commerce**: Extrair catálogos de produtos (nome, preço, SKU, imagens, descrição)
- **Blogs/Portais**: Extrair artigos com título, autor, data, conteúdo
- **Galerias de Imagem**: Baixar todas as imagens em resolução máxima
- **APIs**: Descobrir e documentar endpoints internos do site
- **Marketplaces**: Extrair listagens com todos os campos disponíveis
- **Redes Sociais**: Extrair posts, comentários, metadados públicos

---

## Licença

Uso interno AXION Enterprise.
