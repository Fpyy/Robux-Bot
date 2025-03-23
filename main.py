import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select
from discord import app_commands
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
import os
import asyncio

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Acessa o token do bot
TOKEN = os.getenv("TOKEN")

# Resto do código...
# Função para enviar mensagem para o webhook
async def enviar_webhook(webhook_url, embed, cargos=None, canal_carrinho=None):
    data = {
        "embeds": [embed.to_dict()]
    }
    if cargos:
        data["content"] = cargos  # Adiciona a menção dos cargos
    if canal_carrinho:
        data["embeds"][0].add_field(name="Canal do Carrinho:", value=canal_carrinho.mention, inline=False)
    headers = {
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(webhook_url, data=json.dumps(data), headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para o webhook: {e}")

# Função para gerar o payload PIX
def gerar_payload_pix(chave_pix, valor, nome_recebedor, cidade_recebedor):
    url = "https://gerarqrcodepix.com.br/api/v1"
    params = {
        "nome": nome_recebedor,
        "cidade": cidade_recebedor,
        "valor": valor,
        "saida": "br",  # Retorna o payload BR Code
        "chave": chave_pix
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Verifica se a requisição foi bem-sucedida
        payload_json = response.json()  # Converte a resposta para JSON
        return payload_json.get("brcode", response.text)  # Retorna o valor do campo 'brcode' ou o texto original
    except requests.exceptions.RequestException as e:
        print(f"Erro ao gerar payload PIX: {e}")
        return None

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Permite que o bot veja os membros do servidor

bot = commands.Bot(command_prefix="!", intents=intents)

# Dicionário para armazenar os carrinhos abertos
carrinhos_abertos = {}

# Variável para armazenar a mensagem do painel
painel_message = None

# Função para criar um canal de texto privado
async def create_private_channel(guild, user):
    # Define a categoria onde o canal será criado
    categoria_id = 1340128500228821032  # ID da categoria
    categoria = guild.get_channel(categoria_id)

    if not categoria:
        await user.send("Erro: Categoria não encontrada. Verifique o ID da categoria.")
        return None

    # Cria um cargo temporário para o usuário
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),  # Todos os membros não podem ver o canal
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),  # O usuário pode ver e enviar mensagens
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)  # O bot pode ver e enviar mensagens
    }

    # Adiciona permissão para administradores
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    # Cria o canal na categoria especificada
    channel = await categoria.create_text_channel(
        name=f"🛒・carrinho-{user.name}",
        overwrites=overwrites
    )
    return channel

# Função para enviar o painel de atendimento automático
async def send_painel_atendimento(channel, metodo_compra):
    # Cria a embed
    embed = discord.Embed(
        title="Bem-vindo(a) ao Atendimento automático da Fapy Store!",
        description="Para continuar com a compra, selecione abaixo o método de compra desejado.",
        color=discord.Color.blue()
    )

    if metodo_compra == "gamepass":
        # Cria os botões para Robux via gamepass
        com_taxa = Button(label="Robux com taxa", style=discord.ButtonStyle.red)
        sem_taxa = Button(label="Robux sem taxa", style=discord.ButtonStyle.green)
        cancelar = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)

        # Função de callback para o botão "Robux com taxa"
        async def com_taxa_callback(interaction):
            await interaction.response.defer()
            await interaction.message.delete()  # Apaga a embed anterior
            await send_carrinho_embed(interaction, 45.00)  # 1000 Robux com taxa custam R$ 45,00

        # Função de callback para o botão "Robux sem taxa"
        async def sem_taxa_callback(interaction):
            await interaction.response.defer()
            await interaction.message.delete()  # Apaga a embed anterior
            await send_carrinho_embed(interaction, 35.00)  # 1000 Robux sem taxa custam R$ 35,00

        # Função de callback para o botão "Cancelar compra"
        async def cancelar_callback(interaction):
            await interaction.response.defer()
            await confirmar_cancelamento(interaction)

        # Adiciona os callbacks aos botões
        com_taxa.callback = com_taxa_callback
        sem_taxa.callback = sem_taxa_callback
        cancelar.callback = cancelar_callback

        # Cria a view e envia a embed com os botões
        view = View()
        view.add_item(com_taxa)
        view.add_item(sem_taxa)
        view.add_item(cancelar)
        await channel.send(embed=embed, view=view)
    elif metodo_compra == "grupo":
        # Cria os botões para Robux via grupo (apenas "com taxa")
        com_taxa = Button(label="Robux com taxa", style=discord.ButtonStyle.red)
        sem_taxa = Button(label="Robux sem taxa", style=discord.ButtonStyle.green, disabled=True)  # Botão desabilitado
        cancelar = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)

        # Função de callback para o botão "Robux com taxa"
        async def com_taxa_callback(interaction):
            await interaction.response.defer()
            await interaction.message.delete()  # Apaga a embed anterior
            await send_carrinho_embed(interaction, 45.00)  # 1000 Robux com taxa custam R$ 45,00

        # Função de callback para o botão "Cancelar compra"
        async def cancelar_callback(interaction):
            await interaction.response.defer()
            await confirmar_cancelamento(interaction)

        # Adiciona os callbacks aos botões
        com_taxa.callback = com_taxa_callback
        cancelar.callback = cancelar_callback

        # Cria a view e envia a embed com os botões
        view = View()
        view.add_item(com_taxa)
        view.add_item(sem_taxa)  # Botão "Sem taxa" desabilitado
        view.add_item(cancelar)
        await channel.send(embed=embed, view=view)

# Função para confirmar o cancelamento da compra
async def confirmar_cancelamento(interaction):
    embed = discord.Embed(
        title="Cancelar Compra",
        description="Você realmente deseja fechar o seu carrinho?",
        color=discord.Color.orange()
    )

    sim = Button(label="Sim", style=discord.ButtonStyle.success)
    nao = Button(label="Não", style=discord.ButtonStyle.danger)

    async def sim_callback(interaction):
        await interaction.response.defer()
        await interaction.message.delete()

        # Fecha o carrinho
        if interaction.user.id in carrinhos_abertos:
            channel = carrinhos_abertos[interaction.user.id]
            await channel.delete(reason="Carrinho fechado pelo usuário.")
            del carrinhos_abertos[interaction.user.id]

        await interaction.followup.send("Carrinho fechado. Use o comando novamente para reiniciar o processo.")

    async def nao_callback(interaction):
        await interaction.response.defer()
        await interaction.message.delete()
        await interaction.followup.send("Compra continuada.", ephemeral=True)

    sim.callback = sim_callback
    nao.callback = nao_callback

    view = View()
    view.add_item(sim)
    view.add_item(nao)
    await interaction.followup.send(embed=embed, view=view)

# Função para enviar a embed do carrinho
async def send_carrinho_embed(interaction, preco_por_1000):
    # Cria a embed do carrinho
    embed = discord.Embed(
        title="CARRINHO",
        description="Preencha as informações abaixo para continuar com a compra.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Quantidade de robux desejada:", value="(Aguardando...)", inline=False)
    embed.add_field(name="Valor final:", value="(Aguardando...)", inline=False)

    # Cria os botões
    prosseguir = Button(label="Prosseguir com a compra", style=discord.ButtonStyle.primary)
    retornar = Button(label="Retornar à aba anterior", style=discord.ButtonStyle.secondary)
    cancelar = Button(label="Cancelar a compra", style=discord.ButtonStyle.danger)

    # Função de callback para o botão "Prosseguir com a compra"
    async def prosseguir_callback(interaction):
        await interaction.response.defer()
        await interaction.message.delete()  # Apaga a embed anterior
        await interaction.followup.send("Agora, para finalizarmos sua compra, informe seu nome de usuário do Roblox.")

        # Aguarda o nome de usuário do Roblox
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        while True:
            try:
                msg = await bot.wait_for("message", timeout=60.0, check=check)
                username = msg.content

                # Obtém o ID e o avatar do usuário
                user_id = get_roblox_user_id(username)
                if not user_id:
                    await interaction.followup.send("Não foi possível encontrar o usuário. Verifique o nome de usuário e tente novamente.")
                    continue

                avatar_url = get_roblox_avatar_url(user_id)
                if not avatar_url:
                    await interaction.followup.send("Não foi possível obter o avatar do usuário.")
                    continue

                # Envia a embed com o avatar
                embed = discord.Embed(
                    title="Confirmação de Usuário",
                    description="Este é seu usuário do Roblox?",
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=avatar_url)  # Adiciona o avatar como thumbnail
                embed.set_image(url=avatar_url)

                # Cria os botões de confirmação
                sim = Button(label="Sim", style=discord.ButtonStyle.success)
                nao = Button(label="Não", style=discord.ButtonStyle.danger)

                # Função de callback para o botão "Sim"
                async def sim_callback(interaction):
                    await interaction.response.defer()
                    await interaction.message.delete()  # Apaga a embed anterior

                    # Configurações do PIX
                    CHAVE_PIX = "12423896603"  # Chave PIX (CPF)
                    NOME_RECEBEDOR = "Bernardo"  # Nome do recebedor
                    CIDADE_RECEBEDOR = "Rio de Janeiro"  # Cidade do recebedor

                    # Gera o payload PIX
                    valor_total = (quantidade / 1000) * preco_por_1000
                    payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor_total:.2f}", NOME_RECEBEDOR, CIDADE_RECEBEDOR)

                    if not payload_pix:
                        await interaction.followup.send("Erro ao gerar o pagamento PIX. Tente novamente mais tarde.", ephemeral=True)
                        return

                    # Cria a embed de pagamento
                    embed = discord.Embed(
                        title="## PAGAMENTO VIA PIX",
                        description=f"**Valor:** R$ {valor_total:.2f}\n\nUse o código PIX abaixo para realizar o pagamento:",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)

                    # Cria os botões
                    chave_button = Button(label="Copiar código PIX", style=discord.ButtonStyle.blurple)
                    cancelar_button = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)
                    entregue_button = Button(label="Compra entregue", style=discord.ButtonStyle.success, disabled=False)  # Botão habilitado

                    # Função de callback para o botão "Copiar código PIX"
                    async def chave_callback(interaction):
                        await interaction.response.send_message(f"Código PIX copiado: `{payload_pix}`", ephemeral=True)

                    # Função de callback para o botão "Cancelar compra"
                    async def cancelar_callback(interaction):
                        await confirmar_cancelamento(interaction)

                    # Função de callback para o botão "Compra entregue"
                    async def entregue_callback(interaction):
                        if not interaction.user.guild_permissions.administrator:
                            await interaction.response.send_message("Apenas administradores podem marcar a compra como entregue.", ephemeral=True)
                            return

                        await interaction.response.defer()
                        await interaction.message.delete()

                        # Envia mensagem no privado do comprador
                        comprador = interaction.guild.get_member(interaction.user.id)
                        if comprador:
                            embed_privado = discord.Embed(
                                title="Compra entregue!",
                                description="Sua compra foi entregue com sucesso!",
                                color=discord.Color.green()
                            )
                            embed_privado.add_field(name="Nick de usuário:", value=username, inline=False)
                            embed_privado.add_field(name="Produto:", value=f"{quantidade} Robux", inline=False)
                            embed_privado.add_field(name="Data e hora da entrega:", value=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), inline=False)
                            await comprador.send(embed=embed_privado)

                        # Envia mensagem para o webhook (entrega realizada)
                        webhook_url = "https://discord.com/api/webhooks/1353003630084624414/-mbkAxUmt-xmijNJYI6PP2prJy__R0kZl03djeXckn0LYPk8ebZmjbWD0MLa_8S-fv1A"
                        embed_webhook = discord.Embed(
                            title="Entrega realizada!",
                            color=discord.Color.green()
                        )
                        embed_webhook.add_field(name="Nick de usuário:", value=username, inline=False)
                        embed_webhook.add_field(name="Produto:", value=f"{quantidade} Robux", inline=False)
                        embed_webhook.add_field(name="Entregador:", value=interaction.user.mention, inline=False)
                        embed_webhook.set_thumbnail(url=avatar_url)  # Adiciona o avatar como thumbnail

                        # Marca os cargos
                        cargos = "<@&1340127685346594896> <@&1340343156121800716>"
                        await enviar_webhook(webhook_url, embed_webhook, cargos)

                        # Fecha o carrinho
                        if comprador.id in carrinhos_abertos:
                            channel = carrinhos_abertos[comprador.id]
                            await channel.delete(reason="Compra entregue.")
                            del carrinhos_abertos[comprador.id]

                    # Adiciona os callbacks aos botões
                    chave_button.callback = chave_callback
                    cancelar_button.callback = cancelar_callback
                    entregue_button.callback = entregue_callback

                    # Cria a view e envia a embed com os botões
                    view = View()
                    view.add_item(chave_button)
                    view.add_item(cancelar_button)
                    view.add_item(entregue_button)
                    await interaction.followup.send(embed=embed, view=view)

                    # Envia mensagem para o webhook (compra realizada)
                    webhook_url = "https://discord.com/api/webhooks/1353003630084624414/-mbkAxUmt-xmijNJYI6PP2prJy__R0kZl03djeXckn0LYPk8ebZmjbWD0MLa_8S-fv1A"
                    embed_compra = discord.Embed(
                        title="Compra realizada!",
                        color=discord.Color.blue()
                    )
                    embed_compra.add_field(name="Nick de usuário:", value=username, inline=False)
                    embed_compra.add_field(name="Produto:", value=f"{quantidade} Robux", inline=False)
                    embed_compra.set_thumbnail(url=avatar_url)  # Adiciona o avatar como thumbnail

                    # Marca os cargos
                    cargos = "<@&1340127685346594896> <@&1340343156121800716>"
                    await enviar_webhook(webhook_url, embed_compra, cargos)

                # Função de callback para o botão "Não"
                async def nao_callback(interaction):
                    await interaction.response.defer()
                    await interaction.message.delete()  # Apaga a embed anterior
                    await interaction.followup.send("Agora, para finalizarmos sua compra, informe seu nome de usuário do Roblox.")

                # Adiciona os callbacks aos botões
                sim.callback = sim_callback
                nao.callback = nao_callback

                # Cria a view e envia a embed com os botões
                view = View()
                view.add_item(sim)
                view.add_item(nao)
                await interaction.followup.send(embed=embed, view=view)
                break

            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro: {e}")
                break

    # Função de callback para o botão "Retornar à aba anterior"
    async def retornar_callback(interaction):
        await interaction.response.defer()
        await interaction.message.delete()  # Apaga a embed anterior
        await send_painel_atendimento(interaction.channel, "gamepass")

    # Função de callback para o botão "Cancelar a compra"
    async def cancelar_callback(interaction):
        await interaction.response.defer()
        await confirmar_cancelamento(interaction)

    # Adiciona os callbacks aos botões
    prosseguir.callback = prosseguir_callback
    retornar.callback = retornar_callback
    cancelar.callback = cancelar_callback

    # Cria a view e envia a embed com os botões
    view = View()
    view.add_item(prosseguir)
    view.add_item(retornar)
    view.add_item(cancelar)
    await interaction.followup.send(embed=embed, view=view)

    # Pede a quantidade de Robux
    await interaction.followup.send("Informe a quantidade de Robux que deseja comprar para o preço ser calculado.")

    # Aguarda a quantidade de Robux
    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel

    while True:
        try:
            msg = await bot.wait_for("message", timeout=60.0, check=check)
            quantidade = int(msg.content)

            # Calcula o valor total
            valor_total = (quantidade / 1000) * preco_por_1000

            # Atualiza a embed com o valor calculado
            embed.set_field_at(0, name="Quantidade de robux desejada:", value=f"{quantidade} Robux", inline=False)
            embed.set_field_at(1, name="Valor final:", value=f"R$ {valor_total:.2f}", inline=False)

            # Envia a embed atualizada
            await interaction.followup.send(embed=embed, view=view)
            break
        except ValueError:
            await interaction.followup.send("Por favor, insira um número válido.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro: {e}")
            break

# Função para obter o ID do usuário do Roblox
def get_roblox_user_id(username):
    try:
        url = 'https://users.roblox.com/v1/usernames/users'
        request_body = {
            'usernames': [username],
            'excludeBannedUsers': True
        }
        json_data = json.dumps(request_body)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        response = requests.post(url, headers=headers, data=json_data, timeout=10)
        if response.status_code != 200:
            print(f"Erro ao obter o ID do usuário: {response.status_code}")
            return None
        user_data = json.loads(response.text)
        if len(user_data['data']) > 0:
            user_id = user_data['data'][0]['id']
            return user_id
        else:
            print(f"Usuário **{username}** não encontrado.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return None

# Função para obter a URL do avatar do Roblox
def get_roblox_avatar_url(user_id):
    try:
        url = f"https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds={user_id}&size=180x180&format=Png&isCircular=false"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Erro ao obter a URL do avatar: {response.status_code}")
            return None
        data = response.json()
        image_url = data["data"][0]["imageUrl"]
        return image_url
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return None

# Função para enviar o painel de compras
async def send_painel(ctx):
    # Cria a embed
    embed = discord.Embed(
        title="PAINEL DE COMPRAS",
        description="> Olá, seja bem-vindo ao painel de compras. Para comprar, basta selecionar o que deseja comprar no menu abaixo.",
        color=discord.Color.blue()
    )

    # Adiciona a imagem ao painel de compras
    embed.set_image(url="https://cdn.discordapp.com/attachments/1340143464041414796/1353119422784737381/image.png?ex=67e07e2a&is=67df2caa&hm=c8c0917e08c179224a42511e719e56c248d578c7a35bccd58656b6d67599089b&")

    # Cria o menu de seleção
    select = Select(
        placeholder="Selecione o método de compra",
        options=[
            discord.SelectOption(label="Robux via gamepass", value="gamepass", description="Compre robux via gamepass aqui."),
            discord.SelectOption(label="Robux via grupo", value="grupo", description="Compre robux via grupo aqui.")
        ]
    )

    # Função de callback para o menu de seleção
    async def select_callback(interaction):
        if select.values[0] == "gamepass":
            user_id = interaction.user.id

            # Verifica se o usuário já tem um carrinho aberto
            if user_id in carrinhos_abertos:
                await interaction.response.send_message(
                    f"Erro, você já tem um carrinho aberto em #{carrinhos_abertos[user_id].name}.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message("Gerando carrinho, aguarde...", ephemeral=True)  # Resposta visível apenas para o usuário

            # Cria o canal de texto privado
            channel = await create_private_channel(interaction.guild, interaction.user)

            # Armazena o canal no dicionário de carrinhos abertos
            carrinhos_abertos[user_id] = channel

            # Envia a mensagem de confirmação no canal privado
            await channel.send(f"{interaction.user.mention}, seu carrinho foi criado com sucesso! Siga as instruções de compra abaixo para realizar sua compra, qualquer dúvida, apenas aguarde um administrador entrar em contato <@&1340343156121800716> <@&1340127685346594896>")

            # Envia a mensagem de confirmação para o usuário
            await interaction.followup.send(
                f"Seu carrinho foi aberto em {channel.mention}. Continue sua compra por lá!",
                ephemeral=True
            )

            # Envia o painel de atendimento automático
            await send_painel_atendimento(channel, "gamepass")
        elif select.values[0] == "grupo":
            user_id = interaction.user.id

            # Verifica se o usuário já tem um carrinho aberto
            if user_id in carrinhos_abertos:
                await interaction.response.send_message(
                    f"Erro, você já tem um carrinho aberto em #{carrinhos_abertos[user_id].name}.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message("Gerando carrinho, aguarde...", ephemeral=True)  # Resposta visível apenas para o usuário

            # Cria o canal de texto privado
            channel = await create_private_channel(interaction.guild, interaction.user)

            # Armazena o canal no dicionário de carrinhos abertos
            carrinhos_abertos[user_id] = channel

            # Envia a mensagem de confirmação no canal privado
            await channel.send(f"{interaction.user.mention}, seu carrinho foi criado com sucesso! Siga as instruções de compra abaixo para realizar sua compra, qualquer dúvida, apenas aguarde um administrador entrar em contato <@&1340343156121800716> <@&1340127685346594896>")

            # Envia a mensagem de confirmação para o usuário
            await interaction.followup.send(
                f"Seu carrinho foi aberto em {channel.mention}. Continue sua compra por lá!",
                ephemeral=True
            )

            # Envia o painel de atendimento automático
            await send_painel_atendimento(channel, "grupo")

    # Adiciona o callback ao menu
    select.callback = select_callback

    # Cria a view e envia a embed com o menu
    view = View()
    view.add_item(select)
    return await ctx.send(embed=embed, view=view)

# Tarefa para reenviar o painel a cada 5 minutos
@tasks.loop(minutes=5)
async def reenviar_painel(ctx):
    global painel_message
    if painel_message:
        await painel_message.delete()
    painel_message = await send_painel(ctx)

# Comando !set para enviar o painel de compras
@bot.command()
@commands.has_permissions(administrator=True)  # Restringe o comando a administradores
async def set(ctx):
    global painel_message
    painel_message = await send_painel(ctx)
    reenviar_painel.start(ctx)

# Evento para remover o carrinho do dicionário quando o canal é excluído
@bot.event
async def on_guild_channel_delete(channel):
    for user_id, carrinho in list(carrinhos_abertos.items()):
        if carrinho.id == channel.id:
            del carrinhos_abertos[user_id]
            break

# Evento quando o bot está pronto
@bot.event
async def on_ready():
    print("Bot está online!")  # Mensagem no console quando o bot ficar online
    await bot.tree.sync()  # Sincroniza os comandos slash

# Comando /cobrar para gerar pagamentos personalizados
@bot.tree.command(name="cobrar", description="Gera um pagamento personalizado")
@app_commands.describe(nome_produto="Nome do produto", valor="Valor do produto")
async def cobrar(interaction: discord.Interaction, nome_produto: str, valor: float):
    # Configurações do PIX
    CHAVE_PIX = "12423896603"  # Chave PIX (CPF)
    NOME_RECEBEDOR = "Bernardo"  # Nome do recebedor
    CIDADE_RECEBEDOR = "Rio de Janeiro"  # Cidade do recebedor

    # Gera o payload PIX
    payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor:.2f}", NOME_RECEBEDOR, CIDADE_RECEBEDOR)

    if not payload_pix:
        await interaction.response.send_message("Erro ao gerar o pagamento PIX. Tente novamente mais tarde.", ephemeral=True)
        return

    # Cria a embed de pagamento
    embed = discord.Embed(
        title="## PAGAMENTO VIA PIX",
        description=f"**Produto:** {nome_produto}\n**Valor:** R$ {valor:.2f}\n\nUse o código PIX abaixo para realizar o pagamento:",
        color=discord.Color.green()
    )
    embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)

    # Cria os botões
    chave_button = Button(label="Copiar código PIX", style=discord.ButtonStyle.blurple)
    cancelar_button = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)

    # Função de callback para o botão "Copiar código PIX"
    async def chave_callback(interaction):
        await interaction.response.send_message(f"Código PIX copiado: `{payload_pix}`", ephemeral=True)

    # Função de callback para o botão "Cancelar compra"
    async def cancelar_callback(interaction):
        await interaction.response.defer()
        await interaction.message.delete()

    # Adiciona os callbacks aos botões
    chave_button.callback = chave_callback
    cancelar_button.callback = cancelar_callback

    # Cria a view e envia a embed com os botões
    view = View()
    view.add_item(chave_button)
    view.add_item(cancelar_button)
    await interaction.response.send_message(embed=embed, view=view)

# Inicia o bot
bot.run(os.getenv("TOKEN"))  # Usa a variável de ambiente para o token