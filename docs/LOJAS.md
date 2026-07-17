# Lojas e prioridade de integracao

## Conectadas agora

| Loja | Status | Uso recomendado |
| --- | --- | --- |
| Mercado Livre | Funcionando | Marketplace geral, bom volume e comparacao rapida. |
| Amazon | Funcionando | Marketplace geral, eletronicos, livros, casa e tecnologia. |
| Kabum | Funcionando | Hardware, perifericos, notebooks, smartphones e games. |
| Terabyte | Opcional | Removida do padrao a pedido do usuario. |
| Pichau | Instavel | Retornou manutencao/bloqueio temporario no teste real. |
| Magalu | Bloqueada | Retornou erro 403 no teste real. |
| Casas Bahia | Sem resultados | Retornou pagina valida, mas sem produtos para os termos testados. |
| Americanas | Opcional | Removida do padrao a pedido do usuario. |
| Shopee | Instavel/bloqueada | Precos baixos e cupons, mas bloqueou automacao no teste real. |

## Proximas lojas recomendadas

| Prioridade | Loja | Por que vale integrar |
| --- | --- | --- |
| 1 | AliExpress | Precos agressivos, mas maior risco de bloqueio, prazo e variacao de vendedor. |
| 2 | Carrefour | Marketplace amplo para casa, mercado e eletro. |
| 3 | Fast Shop | Eletronicos premium e eletrodomesticos. |

## Regras para detectar boas ofertas

- Preco numerico valido.
- Produto dentro da faixa configurada pelo usuario.
- Menor preco entre lojas para o mesmo termo pesquisado.
- Historico de preco abaixo do maior valor ja coletado.
- Titulo com sinais de oferta, cupom, desconto, liquidacao ou promocao.

## Fluxo profissional recomendado

1. Pesquisar um termo em varias lojas.
2. Repetir a pesquisa periodicamente para alimentar `historico_precos`.
3. Usar a tela Ofertas para priorizar itens com maior queda percentual.
4. Exportar CSV quando for necessario comparar ou postar ofertas.

## Observacao

Para uma versao profissional de monitoramento 24/7, as lojas prioritarias de
tecnologia sao Kabum, Terabyte, Pichau, Amazon e Mercado Livre. Shopee e
AliExpress exigem tratamento melhor contra bloqueios.
