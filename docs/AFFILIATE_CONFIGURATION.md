# Configuração segura de afiliados

O PromoBot aceita somente Mercado Livre, Amazon e Shopee. O arquivo `.env`
nunca é preenchido automaticamente. Use valores emitidos pelos programas
oficiais das lojas.

| Variável | Loja | Obrigatória | Formato | Exemplo fictício seguro |
|---|---|---:|---|---|
| `AMAZON_ASSOCIATE_TAG` | Amazon | Sim, para geração por tag | tag do Amazon Associados | `minhaloja-20` |
| `AMAZON_AFFILIATE_MAP` | Amazon | Alternativa | `CHAVE=https://...;` | `ASIN_REAL=https://amzn.to/SEU_LINK` |
| `AMAZON_AFFILIATE_TEMPLATE` | Amazon | Alternativa avançada | template HTTPS oficial | `https://www.amazon.com.br/dp/{url}?tag={associate_tag}` |
| `MERCADOLIVRE_AFFILIATE_ID` | Mercado Livre | Somente se exigido pelo template | identificador oficial | `ID_FORNECIDO_PELO_ML` |
| `MERCADOLIVRE_AFFILIATE_MAP` | Mercado Livre | Uma das opções | `MLB...=https://meli.la/...;` | `MLB_REAL=https://meli.la/LINK_OFICIAL` |
| `MERCADOLIVRE_AFFILIATE_TEMPLATE` | Mercado Livre | Uma das opções | template HTTPS oficial | fornecido pela integração oficial |
| `SHOPEE_AFFILIATE_ID` | Shopee | Se exigido pelo método oficial | identificador oficial | `ID_FORNECIDO_PELA_SHOPEE` |
| `SHOPEE_AFFILIATE_MAP` | Shopee | Uma das opções | mapa de links oficiais | `ITEM_REAL=https://s.shopee.com.br/LINK_OFICIAL` |
| `SHOPEE_AFFILIATE_TEMPLATE` | Shopee | Uma das opções | template oficial HTTPS | fornecido pela Shopee |
| `AFFILIATE_CACHE_TTL_HOURS` | Todas | Não | inteiro positivo | `720` |
| `AFFILIATE_PLACEHOLDER_VALUES` | Todas | Não | lista separada por vírgulas | `valor_ficticio,outro_placeholder` |

Quando ausente, o diagnóstico informa `NOT_CONFIGURED` ou
`MANUAL_CONFIGURATION_REQUIRED`. Configuração incompleta retorna
`PARTIALLY_CONFIGURED`. Domínio, template ou valor fictício inválido retorna
`VALIDATION_FAILED`. Somente uma geração local bem-sucedida retorna `VALIDATED`.

Execute:

```text
python -m scripts.setup_affiliates
python -m scripts.diagnose_affiliates
```

O diagnóstico não chama APIs externas e mascara identificadores sensíveis.
Para verificação do Mercado Livre, use o perfil persistente existente; o
PromoBot não tenta contornar CAPTCHA ou autenticação.
