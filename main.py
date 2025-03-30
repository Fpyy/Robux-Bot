import discord
from discord.ext import commands
from discord.ui import Button, View, Select
from discord import app_commands, Embed
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
import os
import asyncio

# Configuração inicial
load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Variáveis globais
carrinhos_abertos = {}
VIEW_TIMEOUT = 300  # 5 minutos
CHAVE_PIX = "12423896603"
WEBHOOK_URL = "https://discord.com/api/webhooks/1353003630084624414/-mbkAxUmt-xmijNJYI6PP2prJy__R0kZl03djeXckn0LYPk8ebZmjbWD0MLa_8S-fv1A"

# Funções auxiliares
async def enviar_webhook(webhook_url, embed, cargos=None, canal_carrinho=None):
    data = {"embeds": [embed.to_dict()]}
    if cargos:
        data["content"] = cargos
    if canal_carrinho:
        data["embeds"][0]["fields"].append({
            "name": "Canal do Carrinho:",
            "value": canal_carrinho.mention,
            "inline": False
        })
    
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar webhook: {e}")

async def purge_messages(channel, limit=10):
    def is_target(m):
        return m.author == bot.user or "carrinho" in m.content.lower()
    try:
        await channel.purge(limit=limit, check=is_target)
    except Exception as e:
        print(f"Erro ao limpar mensagens: {e}")

def gerar_payload_pix(chave_pix, valor, nome_recebedor, cidade_recebedor):
    try:
        response = requests.get(
            "https://gerarqrcodepix.com.br/api/v1",
            params={
                "nome": nome_recebedor,
                "cidade": cidade_recebedor,
                "valor": valor,
                "saida": "br",
                "chave": chave_pix
            }
        )
        return response.json().get("brcode")
    except Exception as e:
        print(f"Erro ao gerar PIX: {e}")
        return None

def get_roblox_user_id(username):
    try:
        response = requests.post(
            'https://users.roblox.com/v1/usernames/users',
            json={'usernames': [username], 'excludeBannedUsers': True},
            headers={'Content-Type': 'application/json'}
        )
        if response.status_code == 200:
            data = response.json()
            return data['data'][0]['id'] if data['data'] else None
    except Exception as e:
        print(f"Erro ao buscar ID do Roblox: {e}")
    return None

def get_roblox_avatar_url(user_id):
    try:
        response = requests.get(
            f"https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds={user_id}&size=180x180&format=Png"
        )
        if response.status_code == 200:
            return response.json()["data"][0]["imageUrl"]
    except Exception as e:
        print(f"Erro ao buscar avatar do Roblox: {e}")
    return None

async def create_private_channel(guild, user):
    try:
        categoria = guild.get_channel(1340128500228821032)
        if not categoria:
            await user.send("Categoria não encontrada!")
            return None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        return await categoria.create_text_channel(
            name=f"🛒・carrinho-{user.name}",
            overwrites=overwrites
        )
    except Exception as e:
        print(f"Erro ao criar canal privado: {e}")
        await user.send("Erro ao criar seu carrinho!")
        return None

async def confirmar_cancelamento(interaction):
    embed = Embed(
        title="Confirmar Cancelamento",
        description="Tem certeza que deseja cancelar a compra?",
        color=discord.Color.orange()
    )
    
    class ConfirmacaoView(View):
        def __init__(self):
            super().__init__(timeout=VIEW_TIMEOUT)
            self.add_item(Button(label="Sim", style=discord.ButtonStyle.danger, custom_id="sim"))
            self.add_item(Button(label="Não", style=discord.ButtonStyle.secondary, custom_id="nao"))
        
        async def interaction_check(self, interaction):
            if interaction.data["custom_id"] == "sim":
                if interaction.user.id in carrinhos_abertos:
                    channel = carrinhos_abertos[interaction.user.id]
                    await channel.delete()
                    del carrinhos_abertos[interaction.user.id]
                await interaction.response.send_message("Compra cancelada!", ephemeral=True)
            else:
                await interaction.response.send_message("Compra mantida!", ephemeral=True)
            await interaction.message.delete()
            return False
    
    await interaction.response.send_message(embed=embed, view=ConfirmacaoView(), ephemeral=True)

# Classes de View
class BaseView(View):
    def __init__(self, *args, **kwargs):
        super().__init__(timeout=VIEW_TIMEOUT, *args, **kwargs)
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

class PainelComprasView(BaseView):
    def __init__(self):
        super().__init__()
        
        select = Select(
            placeholder="Selecione o método de compra",
            options=[
                discord.SelectOption(label="Robux via gamepass", value="gamepass", description="Compre robux via gamepass"),
                discord.SelectOption(label="Robux via grupo", value="grupo", description="Compre robux via grupo")
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction):
        metodo = interaction.data["values"][0]
        await interaction.response.defer()
        
        if interaction.user.id in carrinhos_abertos:
            await interaction.followup.send(
                f"Você já tem um carrinho aberto em {carrinhos_abertos[interaction.user.id].mention}",
                ephemeral=True
            )
            return

        channel = await create_private_channel(interaction.guild, interaction.user)
        if not channel:
            await interaction.followup.send("Erro ao criar carrinho!", ephemeral=True)
            return

        carrinhos_abertos[interaction.user.id] = channel
        await interaction.followup.send(f"Carrinho criado em {channel.mention}", ephemeral=True)
        await channel.send(f"{interaction.user.mention}, bem-vindo ao seu carrinho!")
        await send_painel_atendimento(channel, metodo)

class PainelAtendimentoView(BaseView):
    def __init__(self, metodo_compra):
        super().__init__()
        self.metodo_compra = metodo_compra
        
        if metodo_compra == "gamepass":
            self.add_item(Button(label="Robux com taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa"))
            self.add_item(Button(label="Robux sem taxa (R$35/1k)", style=discord.ButtonStyle.green, custom_id="sem_taxa"))
        elif metodo_compra == "grupo":
            self.add_item(Button(label="Robux com taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa"))
        
        self.add_item(Button(label="Cancelar compra", style=discord.ButtonStyle.danger, custom_id="cancelar", row=1))

    async def interaction_check(self, interaction):
        await interaction.response.defer()
        if interaction.data["custom_id"] == "com_taxa":
            await send_carrinho_embed(interaction, 45.00)
        elif interaction.data["custom_id"] == "sem_taxa":
            await send_carrinho_embed(interaction, 35.00)
        elif interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        return False

class CarrinhoView(BaseView):
    def __init__(self, preco_por_1000, original_message=None):
        super().__init__()
        self.preco_por_1000 = preco_por_1000
        self.quantidade = None
        self.original_message = original_message
        
        self.add_item(Button(label="Prosseguir", style=discord.ButtonStyle.primary, custom_id="prosseguir"))
        self.add_item(Button(label="Voltar", style=discord.ButtonStyle.secondary, custom_id="voltar"))
        self.add_item(Button(label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=1))

    async def interaction_check(self, interaction):
        await interaction.response.defer()
        if interaction.data["custom_id"] == "prosseguir":
            await self.prosseguir_compra(interaction)
        elif interaction.data["custom_id"] == "voltar":
            await purge_messages(interaction.channel)
            await send_painel_atendimento(interaction.channel, "gamepass")
        elif interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        return False

    async def prosseguir_compra(self, interaction):
        await interaction.followup.send("Por favor, informe seu nome de usuário do Roblox:")
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for("message", timeout=60.0, check=check)
            username = msg.content
            user_id = get_roblox_user_id(username)
            
            if not user_id:
                await interaction.followup.send("Usuário não encontrado. Tente novamente.")
                return
            
            avatar_url = get_roblox_avatar_url(user_id)
            if not avatar_url:
                await interaction.followup.send("Erro ao buscar avatar do usuário.")
                return
            
            embed = Embed(
                title="Confirmação de Usuário",
                description=f"Este é o usuário **{username}** do Roblox?",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=avatar_url)
            
            view = ConfirmarUsuarioView(interaction, username, self.quantidade, self.preco_por_1000)
            await interaction.followup.send(embed=embed, view=view)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("Tempo esgotado. Por favor, inicie novamente.")

class ConfirmarUsuarioView(BaseView):
    def __init__(self, interaction, username, quantidade, preco_por_1000):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.preco_por_1000 = preco_por_1000
        
        self.add_item(Button(label="Sim", style=discord.ButtonStyle.success, custom_id="sim"))
        self.add_item(Button(label="Não", style=discord.ButtonStyle.danger, custom_id="nao"))

    async def interaction_check(self, interaction):
        await interaction.response.defer()
        if interaction.data["custom_id"] == "sim":
            await self.processar_pagamento(interaction)
        elif interaction.data["custom_id"] == "nao":
            await interaction.followup.send("Por favor, informe seu nome de usuário novamente:")
        return False

    async def processar_pagamento(self, interaction):
        valor_total = (self.quantidade / 1000) * self.preco_por_1000
        payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor_total:.2f}", "Bernardo", "Rio de Janeiro")
        
        if not payload_pix:
            await interaction.followup.send("Erro ao gerar pagamento. Tente novamente mais tarde.")
            return
        
        embed = Embed(
            title="PAGAMENTO VIA PIX",
            description=f"**Valor:** R$ {valor_total:.2f}\n\nUse o código abaixo:",
            color=discord.Color.green()
        )
        embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)
        
        view = PagamentoView(self.interaction, self.username, self.quantidade, payload_pix)
        await interaction.followup.send(embed=embed, view=view)

class PagamentoView(BaseView):
    def __init__(self, interaction, username, quantidade, payload_pix):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.payload_pix = payload_pix
        
        self.add_item(Button(label="Copiar PIX", style=discord.ButtonStyle.blurple, custom_id="copiar"))
        self.add_item(Button(label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar"))
        self.add_item(Button(label="Entregue", style=discord.ButtonStyle.success, custom_id="entregue", row=1))

    async def interaction_check(self, interaction):
        await interaction.response.defer()
        if interaction.data["custom_id"] == "copiar":
            await interaction.followup.send(f"```{self.payload_pix}```", ephemeral=True)
        elif interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        elif interaction.data["custom_id"] == "entregue":
            await self.marcar_entregue(interaction)
        return False

    async def marcar_entregue(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("Apenas administradores podem marcar como entregue!", ephemeral=True)
            return
        
        comprador = interaction.guild.get_member(self.interaction.user.id)
        if comprador:
            embed = Embed(
                title="✅ Compra Entregue",
                description=f"{comprador.mention}, sua compra foi concluída!",
                color=discord.Color.green()
            )
            embed.add_field(name="Usuário Roblox", value=self.username)
            embed.add_field(name="Quantidade", value=f"{self.quantidade} Robux")
            embed.add_field(name="Valor", value=f"R$ {(self.quantidade/1000)*self.preco_por_1000:.2f}")
            
            try:
                await comprador.send(embed=embed)
            except:
                pass
        
        # Enviar para webhook
        embed_webhook = Embed(
            title="COMPRA FINALIZADA",
            color=discord.Color.gold()
        )
        embed_webhook.add_field(name="Comprador", value=comprador.mention)
        embed_webhook.add_field(name="Roblox", value=self.username)
        embed_webhook.add_field(name="Entregue por", value=interaction.user.mention)
        
        await enviar_webhook(WEBHOOK_URL, embed_webhook, cargos="@everyone")
        
        # Fechar carrinho
        if self.interaction.user.id in carrinhos_abertos:
            try:
                await carrinhos_abertos[self.interaction.user.id].delete()
            except:
                pass
            del carrinhos_abertos[self.interaction.user.id]
        
        await interaction.followup.send("Compra marcada como entregue!", ephemeral=True)

# Funções principais
async def send_painel_atendimento(channel, metodo_compra):
    embed = Embed(
        title="Método de Compra",
        description="Selecione como deseja comprar:",
        color=discord.Color.blue()
    )
    await channel.send(embed=embed, view=PainelAtendimentoView(metodo_compra))

async def send_carrinho_embed(interaction, preco_por_1000):
    embed = Embed(
        title="Seu Carrinho",
        description="Informe a quantidade de Robux:",
        color=discord.Color.blue()
    )
    embed.add_field(name="Preço por 1k", value=f"R$ {preco_por_1000:.2f}")
    embed.add_field(name="Valor total", value="Aguardando...")
    
    view = CarrinhoView(preco_por_1000)
    msg = await interaction.followup.send(embed=embed, view=view, wait=True)
    view.original_message = msg
    
    await interaction.followup.send("Digite a quantidade de Robux que deseja comprar:")
    
    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel
    
    try:
        msg = await bot.wait_for("message", timeout=60.0, check=check)
        quantidade = int(msg.content)
        valor_total = (quantidade / 1000) * preco_por_1000
        
        embed.set_field_at(1, name="Valor total", value=f"R$ {valor_total:.2f}")
        view.quantidade = quantidade
        
        await view.original_message.edit(embed=embed, view=view)
        await msg.delete()
        
    except ValueError:
        await interaction.followup.send("Por favor, digite apenas números!", delete_after=5)
    except Exception as e:
        await interaction.followup.send(f"Erro: {e}", delete_after=5)

# Comandos
@bot.command()
@commands.has_permissions(administrator=True)
async def set(ctx):
    embed = Embed(
        title="PAINEL DE COMPRAS",
        description="Selecione o método de compra abaixo:",
        color=discord.Color.blue()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1340143464041414796/1353119422784737381/image.png")
    await ctx.send(embed=embed, view=PainelComprasView())

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    try:
        await bot.tree.sync()
    except:
        pass

@bot.event
async def on_guild_channel_delete(channel):
    for user_id, carrinho in list(carrinhos_abertos.items()):
        if carrinho.id == channel.id:
            del carrinhos_abertos[user_id]
            break

bot.run(TOKEN)