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
CHAVE_PIX = "12423896603"
WEBHOOK_URL = "https://discord.com/api/webhooks/1353003630084624414/-mbkAxUmt-xmijNJYI6PP2prJy__R0kZl03djeXckn0LYPk8ebZmjbWD0MLa_8S-fv1A"

# Funções auxiliares
async def enviar_webhook(webhook_url, embed, cargos=None, canal_carrinho=None):
    data = {"embeds": [embed.to_dict()]}
    if cargos:
        data["content"] = cargos
    if canal_carrinho:
        data["embeds"][0]["fields"].append({
            "name": "📌 Canal do Carrinho:",
            "value": canal_carrinho.mention,
            "inline": False
        })
    
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao enviar webhook: {e}")

async def purge_messages(channel, limit=10):
    def is_target(m):
        return m.author == bot.user or "carrinho" in m.content.lower()
    try:
        await channel.purge(limit=limit, check=is_target)
    except Exception as e:
        print(f"❌ Erro ao limpar mensagens: {e}")

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
        print(f"❌ Erro ao gerar PIX: {e}")
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
        print(f"❌ Erro ao buscar ID do Roblox: {e}")
    return None

def get_roblox_avatar_url(user_id):
    try:
        response = requests.get(
            f"https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds={user_id}&size=180x180&format=Png"
        )
        if response.status_code == 200:
            return response.json()["data"][0]["imageUrl"]
    except Exception as e:
        print(f"❌ Erro ao buscar avatar do Roblox: {e}")
    return None

async def create_private_channel(guild, user):
    try:
        categoria = guild.get_channel(1340128500228821032)
        if not categoria:
            await user.send("🔴 **Erro:** Categoria não encontrada!")
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
        print(f"❌ Erro ao criar canal privado: {e}")
        await user.send("🔴 **Erro:** Não foi possível criar seu carrinho!")
        return None

async def confirmar_cancelamento(interaction):
    try:
        embed = Embed(
            title="❓ Confirmar Cancelamento",
            description="**Tem certeza que deseja cancelar sua compra?**",
            color=discord.Color.orange()
        )
        embed.set_footer(text="Esta ação não pode ser desfeita!")
        
        class ConfirmacaoView(View):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(Button(label="✅ Sim", style=discord.ButtonStyle.danger))
                self.add_item(Button(label="❌ Não", style=discord.ButtonStyle.secondary))
            
            async def interaction_check(self, interaction):
                if interaction.data["custom_id"] == "✅ Sim":
                    if interaction.user.id in carrinhos_abertos:
                        channel = carrinhos_abertos[interaction.user.id]
                        await channel.delete()
                        del carrinhos_abertos[interaction.user.id]
                    await interaction.response.send_message("🛑 **Compra cancelada com sucesso!**", ephemeral=True)
                else:
                    await interaction.response.send_message("✅ **Compra mantida!**", ephemeral=True)
                await interaction.message.delete()
                return False
        
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=ConfirmacaoView(), ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=ConfirmacaoView(), ephemeral=True)
    except Exception as e:
        print(f"❌ Erro no cancelamento: {e}")

# Classes de View
class BaseView(View):
    def __init__(self, *args, **kwargs):
        super().__init__(timeout=None, *args, **kwargs)

class PainelComprasView(BaseView):
    def __init__(self):
        super().__init__()
        
        select = Select(
            placeholder="🔍 Selecione o método de compra",
            options=[
                discord.SelectOption(label="💰 Robux via Gamepass", value="gamepass", description="Compre Robux via Gamepass"),
                discord.SelectOption(label="👥 Robux via Grupo", value="grupo", description="Compre Robux via Grupo")
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction):
        metodo = interaction.data["values"][0]
        await interaction.response.defer()
        
        if interaction.user.id in carrinhos_abertos:
            await interaction.followup.send(
                f"⚠️ **Você já tem um carrinho aberto em** {carrinhos_abertos[interaction.user.id].mention}",
                ephemeral=True
            )
            return

        channel = await create_private_channel(interaction.guild, interaction.user)
        if not channel:
            await interaction.followup.send("🔴 **Erro:** Não foi possível criar o carrinho!", ephemeral=True)
            return

        carrinhos_abertos[interaction.user.id] = channel
        
        embed = Embed(
            title="🛒 Carrinho Criado!",
            description=f"Olá {interaction.user.mention}, seu carrinho foi criado com sucesso!\n\n"
                       f"📌 **Canal:** {channel.mention}\n"
                       f"⏳ **Tempo limite:** 5 minutos\n"
                       f"🛍️ **Método:** {'Gamepass' if metodo == 'gamepass' else 'Grupo'}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1128606053013176370.webp")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        embed_channel = Embed(
            title=f"🌟 Bem-vindo ao seu Carrinho!",
            description=f"Olá {interaction.user.mention}, vamos começar sua compra!\n\n"
                        f"🔹 **Método selecionado:** {'Gamepass' if metodo == 'gamepass' else 'Grupo'}\n"
                        f"🔹 **Atenção:** Você tem 5 minutos para cada ação\n"
                        f"🔹 **Dúvidas?** Aguarde um atendente",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed_channel)
        await send_painel_atendimento(channel, metodo)

class PainelAtendimentoView(BaseView):
    def __init__(self, metodo_compra):
        super().__init__()
        self.metodo_compra = metodo_compra
        
        if metodo_compra == "gamepass":
            self.add_item(Button(emoji="💸", label="Com Taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa"))
            self.add_item(Button(emoji="💰", label="Sem Taxa (R$35/1k)", style=discord.ButtonStyle.green, custom_id="sem_taxa"))
        elif metodo_compra == "grupo":
            self.add_item(Button(emoji="💸", label="Com Taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa"))
        
        self.add_item(Button(emoji="❌", label="Cancelar Compra", style=discord.ButtonStyle.danger, custom_id="cancelar", row=1))

    async def interaction_check(self, interaction):
        try:
            if interaction.data["custom_id"] == "com_taxa":
                await interaction.response.defer()
                await send_carrinho_embed(interaction, 45.00)
            elif interaction.data["custom_id"] == "sem_taxa":
                await interaction.response.defer()
                await send_carrinho_embed(interaction, 35.00)
            elif interaction.data["custom_id"] == "cancelar":
                await interaction.response.defer()
                await confirmar_cancelamento(interaction)
        except Exception as e:
            print(f"❌ Erro na interação: {e}")

class CarrinhoView(BaseView):
    def __init__(self, preco_por_1000, original_message=None):
        super().__init__()
        self.preco_por_1000 = preco_por_1000
        self.quantidade = None
        self.original_message = original_message
        
        self.add_item(Button(emoji="➡️", label="Prosseguir", style=discord.ButtonStyle.primary, custom_id="prosseguir"))
        self.add_item(Button(emoji="🔙", label="Voltar", style=discord.ButtonStyle.secondary, custom_id="voltar"))
        self.add_item(Button(emoji="❌", label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=1))

    async def interaction_check(self, interaction):
        try:
            if interaction.data["custom_id"] == "prosseguir":
                await interaction.response.defer()
                await self.prosseguir_compra(interaction)
            elif interaction.data["custom_id"] == "voltar":
                await interaction.response.defer()
                await purge_messages(interaction.channel)
                await send_painel_atendimento(interaction.channel, "gamepass")
            elif interaction.data["custom_id"] == "cancelar":
                await interaction.response.defer()
                await confirmar_cancelamento(interaction)
        except Exception as e:
            print(f"❌ Erro no carrinho: {e}")

    async def prosseguir_compra(self, interaction):
        embed = Embed(
            title="🔍 Confirmação de Usuário",
            description="Por favor, **digite seu nome de usuário do Roblox** no chat:",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Você tem 1 minuto para responder")
        await interaction.followup.send(embed=embed)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for("message", timeout=60.0, check=check)
            username = msg.content
            user_id = get_roblox_user_id(username)
            
            if not user_id:
                embed = Embed(
                    title="❌ Usuário não encontrado",
                    description="Não foi possível encontrar esse usuário no Roblox.\nPor favor, digite novamente:",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return
            
            avatar_url = get_roblox_avatar_url(user_id)
            if not avatar_url:
                avatar_url = "https://cdn.discordapp.com/emojis/1128606053013176370.webp"
            
            embed = Embed(
                title="✅ Usuário Encontrado!",
                description=f"Este é o usuário **{username}** do Roblox?\n\n"
                            "Confirme abaixo para prosseguir com o pagamento:",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=avatar_url)
            embed.set_image(url=avatar_url)
            
            view = ConfirmarUsuarioView(interaction, username, self.quantidade, self.preco_por_1000)
            await interaction.followup.send(embed=embed, view=view)
            await msg.delete()
            
        except asyncio.TimeoutError:
            embed = Embed(
                title="⏰ Tempo Esgotado",
                description="Você demorou muito para responder.\nPor favor, inicie novamente o processo.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)

class ConfirmarUsuarioView(BaseView):
    def __init__(self, interaction, username, quantidade, preco_por_1000):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.preco_por_1000 = preco_por_1000
        
        self.add_item(Button(emoji="✅", label="Sim, Continuar", style=discord.ButtonStyle.success, custom_id="sim"))
        self.add_item(Button(emoji="❌", label="Não, Corrigir", style=discord.ButtonStyle.danger, custom_id="nao"))

    async def interaction_check(self, interaction):
        try:
            if interaction.data["custom_id"] == "sim":
                await interaction.response.defer()
                await self.processar_pagamento(interaction)
            elif interaction.data["custom_id"] == "nao":
                await interaction.response.defer()
                embed = Embed(
                    title="🔍 Digite Novamente",
                    description="Por favor, **digite seu nome de usuário do Roblox** novamente:",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"❌ Erro na confirmação: {e}")

    async def processar_pagamento(self, interaction):
        valor_total = (self.quantidade / 1000) * self.preco_por_1000
        payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor_total:.2f}", "Bernardo", "Rio de Janeiro")
        
        if not payload_pix:
            embed = Embed(
                title="❌ Erro no Pagamento",
                description="Não foi possível gerar o código PIX.\nPor favor, tente novamente mais tarde.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = Embed(
            title="💳 PAGAMENTO VIA PIX",
            description=f"**Valor total:** R$ {valor_total:.2f}\n\n"
                       f"📌 **Instruções:**\n"
                       f"1. Abra seu app de pagamentos\n"
                       f"2. Escolha pagar via PIX\n"
                       f"3. Escolha 'PIX Copia e Cola'\n"
                       f"4. Cole o código abaixo\n\n"
                       f"⏳ **Tempo limite:** 30 minutos",
            color=discord.Color.green()
        )
        embed.add_field(name="📋 Código PIX:", value=f"```{payload_pix}```", inline=False)
        embed.set_footer(text="Após o pagamento, aguarde a confirmação!")
        
        view = PagamentoView(self.interaction, self.username, self.quantidade, payload_pix)
        await interaction.followup.send(embed=embed, view=view)

class PagamentoView(BaseView):
    def __init__(self, interaction, username, quantidade, payload_pix):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.payload_pix = payload_pix
        
        self.add_item(Button(emoji="📋", label="Copiar PIX", style=discord.ButtonStyle.blurple, custom_id="copiar"))
        self.add_item(Button(emoji="❌", label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar"))
        self.add_item(Button(emoji="✅", label="Marcar como Entregue", style=discord.ButtonStyle.success, custom_id="entregue", row=1))

    async def interaction_check(self, interaction):
        try:
            if interaction.data["custom_id"] == "copiar":
                await interaction.response.send_message(f"📋 **Código PIX copiado!**\n```{self.payload_pix}```", ephemeral=True)
            elif interaction.data["custom_id"] == "cancelar":
                await interaction.response.defer()
                await confirmar_cancelamento(interaction)
            elif interaction.data["custom_id"] == "entregue":
                await interaction.response.defer()
                await self.marcar_entregue(interaction)
        except Exception as e:
            print(f"❌ Erro no pagamento: {e}")

    async def marcar_entregue(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("🔴 **Erro:** Apenas administradores podem marcar como entregue!", ephemeral=True)
            return
        
        comprador = interaction.guild.get_member(self.interaction.user.id)
        if comprador:
            embed = Embed(
                title="✅ COMPRA FINALIZADA!",
                description=f"{comprador.mention}, sua compra foi concluída com sucesso!\n\n"
                            f"📌 **Detalhes:**\n"
                            f"🔹 **Usuário Roblox:** {self.username}\n"
                            f"🔹 **Quantidade:** {self.quantidade} Robux\n"
                            f"🔹 **Valor Total:** R$ {(self.quantidade/1000)*self.preco_por_1000:.2f}\n"
                            f"🔹 **Entregue por:** {interaction.user.mention}",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1128606053013176370.webp")
            
            try:
                await comprador.send(embed=embed)
            except:
                pass
        
        # Enviar para webhook
        embed_webhook = Embed(
            title="📦 COMPRA CONCLUÍDA",
            description=f"Uma compra foi finalizada por {interaction.user.mention}",
            color=discord.Color.gold()
        )
        embed_webhook.add_field(name="👤 Comprador", value=comprador.mention, inline=True)
        embed_webhook.add_field(name="🎮 Roblox", value=self.username, inline=True)
        embed_webhook.add_field(name="💰 Valor", value=f"R$ {(self.quantidade/1000)*self.preco_por_1000:.2f}", inline=True)
        embed_webhook.add_field(name="🛒 Método", value="Gamepass" if self.preco_por_1000 in [35, 45] else "Grupo", inline=True)
        embed_webhook.add_field(name="🛍️ Quantidade", value=f"{self.quantidade} Robux", inline=True)
        embed_webhook.add_field(name="🔄 Entregue por", value=interaction.user.mention, inline=True)
        
        await enviar_webhook(WEBHOOK_URL, embed_webhook, cargos="@everyone")
        
        # Fechar carrinho
        if self.interaction.user.id in carrinhos_abertos:
            try:
                await carrinhos_abertos[self.interaction.user.id].delete()
            except:
                pass
            del carrinhos_abertos[self.interaction.user.id]
        
        await interaction.followup.send("✅ **Compra marcada como entregue com sucesso!**", ephemeral=True)

# Funções principais
async def send_painel_atendimento(channel, metodo_compra):
    gamepass_msg = "💰 **Gamepass sem taxa** - R$35/1k\n💸 **Gamepass com taxa** - R$45/1k"
    grupo_msg = "💸 **Apenas com taxa** - R$45/1k"
    
    embed = Embed(
        title=f"🛍️ Método de Compra - {'Gamepass' if metodo_compra == 'gamepass' else 'Grupo'}",
        description=f"Selecione como deseja comprar seus Robux:\n\n{gamepass_msg if metodo_compra == 'gamepass' else grupo_msg}",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Clique nos botões abaixo para selecionar")
    await channel.send(embed=embed, view=PainelAtendimentoView(metodo_compra))

async def send_carrinho_embed(interaction, preco_por_1000):
    embed = Embed(
        title="🛒 Seu Carrinho de Compras",
        description="Informe **quantos Robux** você deseja comprar:\n\n"
                   f"💵 **Preço por 1.000 Robux:** R$ {preco_por_1000:.2f}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🔢 Quantidade", value="Digite no chat...", inline=False)
    embed.add_field(name="💲 Valor Total", value="Será calculado automaticamente", inline=False)
    embed.set_footer(text="Você tem 1 minuto para responder")
    
    view = CarrinhoView(preco_por_1000)
    msg = await interaction.followup.send(embed=embed, view=view, wait=True)
    view.original_message = msg
    
    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel
    
    try:
        msg = await bot.wait_for("message", timeout=60.0, check=check)
        quantidade = int(msg.content)
        valor_total = (quantidade / 1000) * preco_por_1000
        
        embed.set_field_at(0, name="🔢 Quantidade", value=f"{quantidade} Robux", inline=False)
        embed.set_field_at(1, name="💲 Valor Total", value=f"R$ {valor_total:.2f}", inline=False)
        embed.description = f"✅ Quantidade definida para **{quantidade} Robux**\n\n💵 **Preço por 1.000 Robux:** R$ {preco_por_1000:.2f}"
        
        view.quantidade = quantidade
        await view.original_message.edit(embed=embed, view=view)
        await msg.delete()
        
    except ValueError:
        embed = Embed(
            title="❌ Valor Inválido",
            description="Por favor, digite **apenas números**!\nExemplo: `5000` para 5.000 Robux",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, delete_after=10)
    except Exception as e:
        embed = Embed(
            title="❌ Erro Inesperado",
            description=f"Ocorreu um erro: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, delete_after=10)

# Comandos
@bot.command()
@commands.has_permissions(administrator=True)
async def set(ctx):
    embed = Embed(
        title="🌟 PAINEL DE COMPRAS - FAPY STORE",
        description="Selecione abaixo como deseja comprar seus Robux:\n\n"
                   "💰 **Via Gamepass** (Com ou sem taxa)\n"
                   "👥 **Via Grupo** (Apenas com taxa)\n\n"
                   "🛒 Clique no menu abaixo para começar!",
        color=discord.Color.blue()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1340143464041414796/1353119422784737381/image.png")
    await ctx.send(embed=embed, view=PainelComprasView())

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
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