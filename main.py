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

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Permite que o bot veja os membros do servidor

bot = commands.Bot(command_prefix="!", intents=intents)

# Dicionário para armazenar os carrinhos abertos
carrinhos_abertos = {}

# Tempo de timeout para as views (em segundos)
VIEW_TIMEOUT = 300  # 5 minutos

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

# Classe para o painel de atendimento automático
class PainelAtendimentoView(View):
    def __init__(self, metodo_compra):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.metodo_compra = metodo_compra
        
        # Adiciona botões conforme o método de compra
        if metodo_compra == "gamepass":
            com_taxa = Button(label="Robux com taxa", style=discord.ButtonStyle.red)
            sem_taxa = Button(label="Robux sem taxa", style=discord.ButtonStyle.green)
            cancelar = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)
            
            com_taxa.callback = self.com_taxa_callback
            sem_taxa.callback = self.sem_taxa_callback
            cancelar.callback = self.cancelar_callback
            
            self.add_item(com_taxa)
            self.add_item(sem_taxa)
            self.add_item(cancelar)
        elif metodo_compra == "grupo":
            com_taxa = Button(label="Robux com taxa", style=discord.ButtonStyle.red)
            sem_taxa = Button(label="Robux sem taxa", style=discord.ButtonStyle.green, disabled=True)
            cancelar = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)
            
            com_taxa.callback = self.com_taxa_callback
            cancelar.callback = self.cancelar_callback
            
            self.add_item(com_taxa)
            self.add_item(sem_taxa)
            self.add_item(cancelar)
    
    async def com_taxa_callback(self, interaction):
        await interaction.response.defer()
        await send_carrinho_embed(interaction, 45.00)
    
    async def sem_taxa_callback(self, interaction):
        await interaction.response.defer()
        await send_carrinho_embed(interaction, 35.00)
    
    async def cancelar_callback(self, interaction):
        await interaction.response.defer()
        await confirmar_cancelamento(interaction)
    
    async def on_timeout(self):
        # Remove os botões quando o tempo acabar
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

# Classe para confirmação de cancelamento
class ConfirmarCancelamentoView(View):
    def __init__(self):
        super().__init__(timeout=VIEW_TIMEOUT)
        
        sim = Button(label="Sim", style=discord.ButtonStyle.success)
        nao = Button(label="Não", style=discord.ButtonStyle.danger)
        
        sim.callback = self.sim_callback
        nao.callback = self.nao_callback
        
        self.add_item(sim)
        self.add_item(nao)
    
    async def sim_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()

        # Fecha o carrinho
        if interaction.user.id in carrinhos_abertos:
            channel = carrinhos_abertos[interaction.user.id]
            await channel.delete(reason="Carrinho fechado pelo usuário.")
            del carrinhos_abertos[interaction.user.id]

        await interaction.followup.send("Carrinho fechado. Use o comando novamente para reiniciar o processo.")
    
    async def nao_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()
        await interaction.followup.send("Compra continuada.", ephemeral=True)
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

# Classe para o carrinho de compras
class CarrinhoView(View):
    def __init__(self, preco_por_1000):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.preco_por_1000 = preco_por_1000
        self.quantidade = None
        
        prosseguir = Button(label="Prosseguir com a compra", style=discord.ButtonStyle.primary)
        retornar = Button(label="Retornar à aba anterior", style=discord.ButtonStyle.secondary)
        cancelar = Button(label="Cancelar a compra", style=discord.ButtonStyle.danger)
        
        prosseguir.callback = self.prosseguir_callback
        retornar.callback = self.retornar_callback
        cancelar.callback = self.cancelar_callback
        
        self.add_item(prosseguir)
        self.add_item(retornar)
        self.add_item(cancelar)
    
    async def prosseguir_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()
        await interaction.followup.send("Agora, para finalizarmos sua compra, informe seu nome de usuário do Roblox.")

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        while True:
            try:
                msg = await bot.wait_for("message", timeout=60.0, check=check)
                username = msg.content

                user_id = get_roblox_user_id(username)
                if not user_id:
                    await interaction.followup.send("Não foi possível encontrar o usuário. Verifique o nome de usuário e tente novamente.")
                    continue

                avatar_url = get_roblox_avatar_url(user_id)
                if not avatar_url:
                    await interaction.followup.send("Não foi possível obter o avatar do usuário.")
                    continue

                embed = discord.Embed(
                    title="Confirmação de Usuário",
                    description="Este é seu usuário do Roblox?",
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=avatar_url)
                embed.set_image(url=avatar_url)

                view = ConfirmarUsuarioView(interaction, username, self.quantidade, self.preco_por_1000)
                await interaction.followup.send(embed=embed, view=view)
                break

            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro: {e}")
                break
    
    async def retornar_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()
        await send_painel_atendimento(interaction.channel, "gamepass")
    
    async def cancelar_callback(self, interaction):
        await interaction.response.defer()
        await confirmar_cancelamento(interaction)
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

# Classe para confirmação de usuário
class ConfirmarUsuarioView(View):
    def __init__(self, interaction, username, quantidade, preco_por_1000):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.preco_por_1000 = preco_por_1000
        
        sim = Button(label="Sim", style=discord.ButtonStyle.success)
        nao = Button(label="Não", style=discord.ButtonStyle.danger)
        
        sim.callback = self.sim_callback
        nao.callback = self.nao_callback
        
        self.add_item(sim)
        self.add_item(nao)
    
    async def sim_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()

        # Configurações do PIX
        CHAVE_PIX = "12423896603"
        NOME_RECEBEDOR = "Bernardo"
        CIDADE_RECEBEDOR = "Rio de Janeiro"

        valor_total = (self.quantidade / 1000) * self.preco_por_1000
        payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor_total:.2f}", NOME_RECEBEDOR, CIDADE_RECEBEDOR)

        if not payload_pix:
            await interaction.followup.send("Erro ao gerar o pagamento PIX. Tente novamente mais tarde.", ephemeral=True)
            return

        embed = discord.Embed(
            title="## PAGAMENTO VIA PIX",
            description=f"**Valor:** R$ {valor_total:.2f}\n\nUse o código PIX abaixo para realizar o pagamento:",
            color=discord.Color.green()
        )
        embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)

        view = PagamentoView(self.interaction, self.username, self.quantidade, payload_pix)
        await interaction.followup.send(embed=embed, view=view)
    
    async def nao_callback(self, interaction):
        await interaction.response.defer()
        await interaction.message.delete()
        await interaction.followup.send("Por favor, informe novamente seu nome de usuário do Roblox.")
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

# Classe para pagamento
class PagamentoView(View):
    def __init__(self, interaction, username, quantidade, payload_pix):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.payload_pix = payload_pix
        
        chave_button = Button(label="Copiar código PIX", style=discord.ButtonStyle.blurple)
        cancelar_button = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)
        entregue_button = Button(label="Compra entregue", style=discord.ButtonStyle.success, disabled=False)
        
        chave_button.callback = self.chave_callback
        cancelar_button.callback = self.cancelar_callback
        entregue_button.callback = self.entregue_callback
        
        self.add_item(chave_button)
        self.add_item(cancelar_button)
        self.add_item(entregue_button)
    
    async def chave_callback(self, interaction):
        await interaction.response.send_message(f"Código PIX copiado: `{self.payload_pix}`", ephemeral=True)
    
    async def cancelar_callback(self, interaction):
        await confirmar_cancelamento(interaction)
    
    async def entregue_callback(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Apenas administradores podem marcar a compra como entregue.", ephemeral=True)
            return

        await interaction.response.defer()
        await interaction.message.delete()

        # Envia mensagem no privado do comprador
        comprador = interaction.guild.get_member(self.interaction.user.id)
        if comprador:
            embed_privado = discord.Embed(
                title="Compra entregue!",
                description="Sua compra foi entregue com sucesso!",
                color=discord.Color.green()
            )
            embed_privado.add_field(name="Nick de usuário:", value=self.username, inline=False)
            embed_privado.add_field(name="Produto:", value=f"{self.quantidade} Robux", inline=False)
            embed_privado.add_field(name="Data e hora da entrega:", value=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), inline=False)
            await comprador.send(embed=embed_privado)

        # Envia mensagem para o webhook
        webhook_url = "https://discord.com/api/webhooks/1353003630084624414/-mbkAxUmt-xmijNJYI6PP2prJy__R0kZl03djeXckn0LYPk8ebZmjbWD0MLa_8S-fv1A"
        embed_webhook = discord.Embed(
            title="Entrega realizada!",
            color=discord.Color.green()
        )
        embed_webhook.add_field(name="Nick de usuário:", value=self.username, inline=False)
        embed_webhook.add_field(name="Produto:", value=f"{self.quantidade} Robux", inline=False)
        embed_webhook.add_field(name="Entregador:", value=interaction.user.mention, inline=False)

        # Marca os cargos
        cargos = "<@&1340127685346594896> <@&1340343156121800716>"
        await enviar_webhook(webhook_url, embed_webhook, cargos)

        # Fecha o carrinho
        if comprador.id in carrinhos_abertos:
            channel = carrinhos_abertos[comprador.id]
            await channel.delete(reason="Compra entregue.")
            del carrinhos_abertos[comprador.id]
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

# Classe para o painel de compras
class PainelComprasView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Sem timeout para o painel principal
        
        select = Select(
            placeholder="Selecione o método de compra",
            options=[
                discord.SelectOption(label="Robux via gamepass", value="gamepass", description="Compre robux via gamepass aqui."),
                discord.SelectOption(label="Robux via grupo", value="grupo", description="Compre robux via grupo aqui.")
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction):
        if self.children[0].values[0] == "gamepass":
            await self.processar_carrinho(interaction, "gamepass")
        elif self.children[0].values[0] == "grupo":
            await self.processar_carrinho(interaction, "grupo")
    
    async def processar_carrinho(self, interaction, metodo):
        user_id = interaction.user.id

        if user_id in carrinhos_abertos:
            await interaction.response.send_message(
                f"Erro, você já tem um carrinho aberto em #{carrinhos_abertos[user_id].name}.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("Gerando carrinho, aguarde...", ephemeral=True)

        channel = await create_private_channel(interaction.guild, interaction.user)
        carrinhos_abertos[user_id] = channel

        await channel.send(f"{interaction.user.mention}, seu carrinho foi criado com sucesso! Siga as instruções de compra abaixo para realizar sua compra, qualquer dúvida, apenas aguarde um administrador entrar em contato <@&1340343156121800716> <@&1340127685346594896>")
        await interaction.followup.send(f"Seu carrinho foi aberto em {channel.mention}. Continue sua compra por lá!", ephemeral=True)
        await send_painel_atendimento(channel, metodo)

# Função para enviar o painel de atendimento automático
async def send_painel_atendimento(channel, metodo_compra):
    embed = discord.Embed(
        title="Bem-vindo(a) ao Atendimento automático da Fapy Store!",
        description="Para continuar com a compra, selecione abaixo o método de compra desejado.",
        color=discord.Color.blue()
    )
    view = PainelAtendimentoView(metodo_compra)
    await channel.send(embed=embed, view=view)

# Função para confirmar o cancelamento da compra
async def confirmar_cancelamento(interaction):
    embed = discord.Embed(
        title="Cancelar Compra",
        description="Você realmente deseja fechar o seu carrinho?",
        color=discord.Color.orange()
    )
    view = ConfirmarCancelamentoView()
    await interaction.followup.send(embed=embed, view=view)

# Função para enviar a embed do carrinho
async def send_carrinho_embed(interaction, preco_por_1000):
    embed = discord.Embed(
        title="CARRINHO",
        description="Preencha as informações abaixo para continuar com a compra.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Quantidade de robux desejada:", value="(Aguardando...)", inline=False)
    embed.add_field(name="Valor final:", value="(Aguardando...)", inline=False)

    view = CarrinhoView(preco_por_1000)
    await interaction.followup.send(embed=embed, view=view)
    await interaction.followup.send("Informe a quantidade de Robux que deseja comprar para o preço ser calculado.")

    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel

    while True:
        try:
            msg = await bot.wait_for("message", timeout=60.0, check=check)
            quantidade = int(msg.content)
            valor_total = (quantidade / 1000) * preco_por_1000

            view.quantidade = quantidade  # Atualiza a quantidade na view
            
            embed.set_field_at(0, name="Quantidade de robux desejada:", value=f"{quantidade} Robux", inline=False)
            embed.set_field_at(1, name="Valor final:", value=f"R$ {valor_total:.2f}", inline=False)
            
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
    embed = discord.Embed(
        title="PAINEL DE COMPRAS",
        description="> Olá, seja bem-vindo ao painel de compras. Para comprar, basta selecionar o que deseja comprar no menu abaixo.",
        color=discord.Color.blue()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1340143464041414796/1353119422784737381/image.png?ex=67e07e2a&is=67df2caa&hm=c8c0917e08c179224a42511e719e56c248d578c7a35bccd58656b6d67599089b&")
    
    view = PainelComprasView()
    await ctx.send(embed=embed, view=view)
    return await ctx.send(embed=embed, view=view)

# Comando !set para enviar o painel de compras
@bot.command()
@commands.has_permissions(administrator=True)
async def set(ctx):
    await send_painel(ctx)

# Evento para remover o carrinho do dicionário quando o canal é excluído
@bot.event
async def on_guild_channel_delete(channel):
    for user_id, carrinho in list(carrinhos_abertos.items()):
        if carrinho.id == channel.id:
            del carrinhos_abertos[user_id]
            break

# Comando /cobrar para gerar pagamentos personalizados
@bot.tree.command(name="cobrar", description="Gera um pagamento personalizado")
@app_commands.describe(nome_produto="Nome do produto", valor="Valor do produto")
async def cobrar(interaction: discord.Interaction, nome_produto: str, valor: float):
    CHAVE_PIX = "12423896603"
    NOME_RECEBEDOR = "Bernardo"
    CIDADE_RECEBEDOR = "Rio de Janeiro"

    payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor:.2f}", NOME_RECEBEDOR, CIDADE_RECEBEDOR)

    if not payload_pix:
        await interaction.response.send_message("Erro ao gerar o pagamento PIX. Tente novamente mais tarde.", ephemeral=True)
        return

    embed = discord.Embed(
        title="## PAGAMENTO VIA PIX",
        description=f"**Produto:** {nome_produto}\n**Valor:** R$ {valor:.2f}\n\nUse o código PIX abaixo para realizar o pagamento:",
        color=discord.Color.green()
    )
    embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)

    class CobrancaView(View):
        def __init__(self):
            super().__init__(timeout=VIEW_TIMEOUT)
            
            chave_button = Button(label="Copiar código PIX", style=discord.ButtonStyle.blurple)
            cancelar_button = Button(label="Cancelar compra", style=discord.ButtonStyle.danger)
            
            chave_button.callback = self.chave_callback
            cancelar_button.callback = self.cancelar_callback
            
            self.add_item(chave_button)
            self.add_item(cancelar_button)
        
        async def chave_callback(self, interaction):
            await interaction.response.send_message(f"Código PIX copiado: `{payload_pix}`", ephemeral=True)
        
        async def cancelar_callback(self, interaction):
            await interaction.response.defer()
            await interaction.message.delete()
        
        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            await self.message.edit(view=self)

    view = CobrancaView()
    await interaction.response.send_message(embed=embed, view=view)

# Evento quando o bot está pronto
@bot.event
async def on_ready():
    print("Bot está online!")
    await bot.tree.sync()

# Inicia o bot
bot.run(TOKEN)