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

# Carrega as variáveis de ambiente
load_dotenv()
TOKEN = os.getenv("TOKEN")

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Variáveis globais
carrinhos_abertos = {}
VIEW_TIMEOUT = 300  # 5 minutos

# Funções auxiliares
async def enviar_webhook(webhook_url, embed, cargos=None, canal_carrinho=None):
    data = {"embeds": [embed.to_dict()]}
    if cargos:
        data["content"] = cargos
    if canal_carrinho:
        data["embeds"][0].add_field(name="Canal do Carrinho:", value=canal_carrinho.mention, inline=False)
    
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

async def create_private_channel(guild, user):
    categoria = guild.get_channel(1340128500228821032)
    if not categoria:
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

class PainelAtendimentoView(BaseView):
    def __init__(self, metodo_compra):
        super().__init__()
        self.metodo_compra = metodo_compra
        
        if metodo_compra == "gamepass":
            self.add_item(Button(label="Robux com taxa", style=discord.ButtonStyle.red, custom_id="com_taxa"))
            self.add_item(Button(label="Robux sem taxa", style=discord.ButtonStyle.green, custom_id="sem_taxa"))
        elif metodo_compra == "grupo":
            btn = Button(label="Robux com taxa", style=discord.ButtonStyle.red, custom_id="com_taxa")
            btn.disabled = metodo_compra == "grupo"
            self.add_item(btn)
        
        self.add_item(Button(label="Cancelar compra", style=discord.ButtonStyle.danger, custom_id="cancelar"))

    async def interaction_check(self, interaction):
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
        
        self.add_item(Button(label="Prosseguir com a compra", style=discord.ButtonStyle.primary, custom_id="prosseguir"))
        self.add_item(Button(label="Retornar à aba anterior", style=discord.ButtonStyle.secondary, custom_id="retornar"))
        self.add_item(Button(label="Cancelar a compra", style=discord.ButtonStyle.danger, custom_id="cancelar"))

    async def interaction_check(self, interaction):
        if interaction.data["custom_id"] == "prosseguir":
            await self.prosseguir_compra(interaction)
        elif interaction.data["custom_id"] == "retornar":
            await purge_messages(interaction.channel)
            await send_painel_atendimento(interaction.channel, "gamepass")
        elif interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        return False

    async def prosseguir_compra(self, interaction):
        await interaction.response.send_message("Informe seu nome de usuário do Roblox:")
        
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
            embed = discord.Embed(
                title="Confirmação de Usuário",
                description="Este é seu usuário do Roblox?",
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
        if interaction.data["custom_id"] == "sim":
            await self.processar_pagamento(interaction)
        elif interaction.data["custom_id"] == "nao":
            await interaction.response.send_message("Informe novamente seu nome de usuário:")
        return False

    async def processar_pagamento(self, interaction):
        valor_total = (self.quantidade / 1000) * self.preco_por_1000
        payload_pix = gerar_payload_pix("12423896603", f"{valor_total:.2f}", "Bernardo", "Rio de Janeiro")
        
        embed = discord.Embed(
            title="## PAGAMENTO VIA PIX",
            description=f"**Valor:** R$ {valor_total:.2f}\n\nUse o código PIX abaixo:",
            color=discord.Color.green()
        )
        embed.add_field(name="Código PIX:", value=f"`{payload_pix}`", inline=False)
        
        view = PagamentoView(self.interaction, self.username, self.quantidade, payload_pix)
        await interaction.response.send_message(embed=embed, view=view)

class PagamentoView(BaseView):
    def __init__(self, interaction, username, quantidade, payload_pix):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.payload_pix = payload_pix
        
        self.add_item(Button(label="Copiar código PIX", style=discord.ButtonStyle.blurple, custom_id="copiar"))
        self.add_item(Button(label="Cancelar compra", style=discord.ButtonStyle.danger, custom_id="cancelar"))
        self.add_item(Button(label="Compra entregue", style=discord.ButtonStyle.success, custom_id="entregue"))

    async def interaction_check(self, interaction):
        if interaction.data["custom_id"] == "copiar":
            await interaction.response.send_message(f"Código PIX: `{self.payload_pix}`", ephemeral=True)
        elif interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        elif interaction.data["custom_id"] == "entregue":
            await self.marcar_entregue(interaction)
        return False

    async def marcar_entregue(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Apenas administradores podem usar esta função.", ephemeral=True)
            return
        
        comprador = interaction.guild.get_member(self.interaction.user.id)
        if comprador:
            embed = discord.Embed(
                title="Compra entregue!",
                color=discord.Color.green()
            )
            # ... (restante da lógica de entrega)

# Funções principais
async def send_painel_atendimento(channel, metodo_compra):
    embed = discord.Embed(
        title="Bem-vindo ao Atendimento Automático",
        description="Selecione o método de compra:",
        color=discord.Color.blue()
    )
    await channel.send(embed=embed, view=PainelAtendimentoView(metodo_compra))

async def send_carrinho_embed(interaction, preco_por_1000):
    embed = discord.Embed(
        title="CARRINHO",
        description="Preencha as informações abaixo:",
        color=discord.Color.blue()
    )
    embed.add_field(name="Quantidade de robux:", value="(Aguardando...)", inline=False)
    embed.add_field(name="Valor final:", value="(Aguardando...)", inline=False)
    
    view = CarrinhoView(preco_por_1000)
    msg = await interaction.followup.send(embed=embed, view=view, wait=True)
    view.original_message = msg
    
    await interaction.followup.send("Informe a quantidade de Robux desejada:")
    
    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel
    
    try:
        msg = await bot.wait_for("message", timeout=60.0, check=check)
        quantidade = int(msg.content)
        valor_total = (quantidade / 1000) * preco_por_1000
        
        embed.set_field_at(0, name="Quantidade de robux:", value=f"{quantidade} Robux", inline=False)
        embed.set_field_at(1, name="Valor final:", value=f"R$ {valor_total:.2f}", inline=False)
        
        await view.original_message.edit(embed=embed, view=view)
        await msg.delete()
        
    except ValueError:
        await interaction.followup.send("Valor inválido. Use apenas números.", delete_after=5)
    except Exception as e:
        await interaction.followup.send(f"Erro: {str(e)}", delete_after=5)

# Comandos e eventos
@bot.command()
@commands.has_permissions(administrator=True)
async def set(ctx):
    embed = discord.Embed(
        title="PAINEL DE COMPRAS",
        description="Selecione o método de compra:",
        color=discord.Color.blue()
    )
    view = PainelComprasView()
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    await bot.tree.sync()

bot.run(TOKEN)