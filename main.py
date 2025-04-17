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

# Cores e emojis personalizados
EMBED_COLOR = 0xffffff  # Branco
EMOJIS = {
    "loading": "<a:white:1359645236472844609>",
    "success": "<:checkmark_correto:1359653313230143710>",
    "error": "<:checkmark_errado:1359653335862350005>",
    "money": "<:robux:1359653325213270199>",
    "cart": "🛒",
    "info": "ℹ️",
    "warning": "⚠️",
    "gamepass": "🎮",
    "group": "👥"
}

# Banner URLs
BANNERS = {
    "welcome": "https://cdn.discordapp.com/attachments/1340143464041414796/1362539280454652115/1744651990823.jpg?ex=6802c317&is=68017197&hm=c5c8689bc69de9d5025b634a6966fe7b67e43dd0c7462a40a87bfe1dd372bd50&",
    "payment": "https://cdn.discordapp.com/attachments/1340143464041414796/1362539280982868138/1_9f5676ae-f373-4bfd-8e1a-d774081aee54.jpg?ex=6802c317&is=68017197&hm=34c7a219ec38c3816027f6b218fc7ec7d2c5af310db60a4121914c143192e1c2&"
}

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
        print(f"{EMOJIS['error']} Erro ao enviar webhook: {e}")

async def purge_messages(channel, limit=10):
    def is_target(m):
        return m.author == bot.user or "carrinho" in m.content.lower()
    try:
        await channel.purge(limit=limit, check=is_target)
    except Exception as e:
        print(f"{EMOJIS['error']} Erro ao limpar mensagens: {e}")

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
        print(f"{EMOJIS['error']} Erro ao gerar PIX: {e}")
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
        print(f"{EMOJIS['error']} Erro ao buscar ID do Roblox: {e}")
    return None

def get_roblox_avatar_url(user_id):
    try:
        response = requests.get(
            f"https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds={user_id}&size=180x180&format=Png"
        )
        if response.status_code == 200:
            return response.json()["data"][0]["imageUrl"]
    except Exception as e:
        print(f"{EMOJIS['error']} Erro ao buscar avatar do Roblox: {e}")
    return None

async def create_private_channel(guild, user):
    try:
        categoria = guild.get_channel(1340128500228821032)
        if not categoria:
            await user.send(f"{EMOJIS['error']} **Erro:** Categoria não encontrada!")
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
            name=f"{EMOJIS['cart']}・carrinho-{user.name}",
            overwrites=overwrites
        )
    except Exception as e:
        print(f"{EMOJIS['error']} Erro ao criar canal privado: {e}")
        await user.send(f"{EMOJIS['error']} **Erro:** Não foi possível criar seu carrinho!")
        return None

async def confirmar_cancelamento(interaction):
    try:
        embed = Embed(
            title=f"{EMOJIS['warning']} Confirmar Cancelamento",
            description="**Tem certeza que deseja cancelar sua compra?**",
            color=EMBED_COLOR
        )
        embed.set_footer(text="Esta ação não pode ser desfeita!")
        
        class ConfirmacaoView(View):
            def __init__(self):
                super().__init__(timeout=60)
            
            @discord.ui.button(label="✅ Sim", style=discord.ButtonStyle.danger)
            async def confirmar(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                if button_interaction.user != interaction.user:
                    await button_interaction.response.send_message(f"{EMOJIS['error']} Você não pode interagir com este botão!", ephemeral=True)
                    return
                
                if interaction.user.id in carrinhos_abertos:
                    channel = carrinhos_abertos[interaction.user.id]
                    await channel.delete()
                    del carrinhos_abertos[interaction.user.id]
                
                await button_interaction.response.send_message(
                    f"{EMOJIS['success']} **Compra cancelada com sucesso!**", 
                    ephemeral=True
                )
                await interaction.message.delete()
            
            @discord.ui.button(label="❌ Não", style=discord.ButtonStyle.secondary)
            async def cancelar(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                if button_interaction.user != interaction.user:
                    await button_interaction.response.send_message(f"{EMOJIS['error']} Você não pode interagir com este botão!", ephemeral=True)
                    return
                
                await button_interaction.response.send_message(
                    f"{EMOJIS['success']} **Compra mantida!**", 
                    ephemeral=True
                )
                await interaction.message.delete()
        
        await interaction.response.send_message(embed=embed, view=ConfirmacaoView(), ephemeral=True)
    except Exception as e:
        print(f"{EMOJIS['error']} Erro no cancelamento: {e}")

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
                discord.SelectOption(label=f"{EMOJIS['gamepass']} Robux via Gamepass", value="gamepass", description="Compre Robux via Gamepass"),
                discord.SelectOption(label=f"{EMOJIS['group']} Robux via Grupo", value="grupo", description="Compre Robux via Grupo")
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        metodo = interaction.data["values"][0]
        await interaction.response.defer()
        
        if interaction.user.id in carrinhos_abertos:
            await interaction.followup.send(
                f"{EMOJIS['warning']} **Você já tem um carrinho aberto em** {carrinhos_abertos[interaction.user.id].mention}",
                ephemeral=True
            )
            return

        channel = await create_private_channel(interaction.guild, interaction.user)
        if not channel:
            await interaction.followup.send(f"{EMOJIS['error']} **Erro:** Não foi possível criar o carrinho!", ephemeral=True)
            return

        carrinhos_abertos[interaction.user.id] = channel
        
        embed = Embed(
            title=f"{EMOJIS['cart']} Carrinho Criado!",
            description=f"Olá {interaction.user.mention}, seu carrinho foi criado com sucesso!\n\n"
                       f"**📌 Canal:** {channel.mention}\n"
                       f"**⏳ Tempo limite:** 5 minutos\n"
                       f"**🛍️ Método:** {'Gamepass' if metodo == 'gamepass' else 'Grupo'}",
            color=EMBED_COLOR
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1128606053013176370.webp")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        embed_channel = Embed(
            title=f"{EMOJIS['loading']} Bem-vindo ao seu Carrinho!",
            description=f"Olá {interaction.user.mention}, vamos começar sua compra!\n\n"
                       f"**🔹 Método selecionado:** {'Gamepass' if metodo == 'gamepass' else 'Grupo'}\n"
                       f"**🔹 Atenção:** Você tem 5 minutos para cada ação\n"
                       f"**🔹 Dúvidas?** Aguarde um atendente",
            color=EMBED_COLOR
        )
        embed_channel.set_image(url=BANNERS["welcome"])
        await channel.send(embed=embed_channel)
        await send_painel_atendimento(channel, metodo)

class PainelAtendimentoView(BaseView):
    def __init__(self, metodo_compra):
        super().__init__()
        self.metodo_compra = metodo_compra
        
        if metodo_compra == "gamepass":
            self.add_item(Button(emoji="💸", label="Com Taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa", row=0))
            self.add_item(Button(emoji="💰", label="Sem Taxa (R$35/1k)", style=discord.ButtonStyle.green, custom_id="sem_taxa", row=0))
            self.add_item(Button(emoji="❌", label="Cancelar Compra", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))
        elif metodo_compra == "grupo":
            self.add_item(Button(emoji="💸", label="Com Taxa (R$45/1k)", style=discord.ButtonStyle.red, custom_id="com_taxa", row=0))
            self.add_item(Button(emoji="❌", label="Cancelar Compra", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))

    async def interaction_check(self, interaction: discord.Interaction):
        try:
            if interaction.data["custom_id"] == "com_taxa":
                await interaction.response.defer()
                await send_carrinho_embed(interaction, 45.00)
            elif interaction.data["custom_id"] == "sem_taxa":
                await interaction.response.defer()
                await send_carrinho_embed(interaction, 35.00)
            elif interaction.data["custom_id"] == "cancelar":
                await confirmar_cancelamento(interaction)
        except Exception as e:
            print(f"{EMOJIS['error']} Erro na interação: {e}")

class CarrinhoView(BaseView):
    def __init__(self, preco_por_1000, original_message=None):
        super().__init__()
        self.preco_por_1000 = preco_por_1000
        self.quantidade = None
        self.original_message = original_message
        
        self.add_item(Button(emoji="➡️", label="Prosseguir", style=discord.ButtonStyle.primary, custom_id="prosseguir", row=0))
        self.add_item(Button(emoji="🔙", label="Voltar", style=discord.ButtonStyle.secondary, custom_id="voltar", row=0))
        self.add_item(Button(emoji="❌", label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))

    async def interaction_check(self, interaction: discord.Interaction):
        try:
            if interaction.data["custom_id"] == "prosseguir":
                await interaction.response.defer()
                await self.prosseguir_compra(interaction)
            elif interaction.data["custom_id"] == "voltar":
                await interaction.response.defer()
                await purge_messages(interaction.channel)
                await send_painel_atendimento(interaction.channel, "gamepass")
            elif interaction.data["custom_id"] == "cancelar":
                await confirmar_cancelamento(interaction)
        except Exception as e:
            print(f"{EMOJIS['error']} Erro no carrinho: {e}")

    async def prosseguir_compra(self, interaction: discord.Interaction):
        embed = Embed(
            title=f"{EMOJIS['info']} Confirmação de Usuário",
            description="Por favor, **digite seu nome de usuário do Roblox** no chat:",
            color=EMBED_COLOR
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
                    title=f"{EMOJIS['error']} Usuário não encontrado",
                    description="Não foi possível encontrar esse usuário no Roblox.\nPor favor, digite novamente:",
                    color=EMBED_COLOR
                )
                msg = await interaction.followup.send(embed=embed)
                
                try:
                    msg2 = await bot.wait_for("message", timeout=60.0, check=check)
                    username = msg2.content
                    user_id = get_roblox_user_id(username)
                    
                    if not user_id:
                        await interaction.followup.send(f"{EMOJIS['error']} **Usuário não encontrado novamente. Processo cancelado.**", ephemeral=True)
                        return
                    
                    await msg2.delete()
                except asyncio.TimeoutError:
                    await interaction.followup.send(f"{EMOJIS['error']} **Tempo esgotado. Processo cancelado.**", ephemeral=True)
                    return
                
                await msg.delete()
            
            avatar_url = get_roblox_avatar_url(user_id)
            if not avatar_url:
                avatar_url = "https://cdn.discordapp.com/emojis/1128606053013176370.webp"
            
            embed = Embed(
                title=f"{EMOJIS['success']} Usuário Encontrado!",
                description=f"Este é o usuário **{username}** do Roblox?\n\n"
                           "Confirme abaixo para prosseguir com o pagamento:",
                color=EMBED_COLOR
            )
            embed.set_thumbnail(url=avatar_url)
            embed.set_image(url=avatar_url)
            
            view = ConfirmarUsuarioView(interaction, username, self.quantidade, self.preco_por_1000)
            await interaction.followup.send(embed=embed, view=view)
            
        except asyncio.TimeoutError:
            embed = Embed(
                title=f"{EMOJIS['error']} Tempo Esgotado",
                description="Você demorou muito para responder.\nPor favor, inicie novamente o processo.",
                color=EMBED_COLOR
            )
            await interaction.followup.send(embed=embed)

class ConfirmarUsuarioView(BaseView):
    def __init__(self, interaction, username, quantidade, preco_por_1000):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.preco_por_1000 = preco_por_1000
        
        self.add_item(Button(emoji=EMOJIS['success'], label="Sim, Continuar", style=discord.ButtonStyle.success, custom_id="sim", row=0))
        self.add_item(Button(emoji=EMOJIS['error'], label="Não, Corrigir", style=discord.ButtonStyle.danger, custom_id="nao", row=0))

    async def interaction_check(self, interaction: discord.Interaction):
        try:
            if interaction.data["custom_id"] == "sim":
                await interaction.response.defer()
                await self.processar_pagamento(interaction)
            elif interaction.data["custom_id"] == "nao":
                await interaction.response.defer()
                await self.corrigir_usuario(interaction)
        except Exception as e:
            print(f"{EMOJIS['error']} Erro na confirmação: {e}")

    async def corrigir_usuario(self, interaction: discord.Interaction):
        embed = Embed(
            title=f"{EMOJIS['info']} Digite Novamente",
            description="Por favor, **digite seu nome de usuário do Roblox** novamente:",
            color=EMBED_COLOR
        )
        await interaction.followup.send(embed=embed)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for("message", timeout=60.0, check=check)
            username = msg.content
            user_id = get_roblox_user_id(username)
            
            if not user_id:
                embed = Embed(
                    title=f"{EMOJIS['error']} Usuário não encontrado",
                    description="Não foi possível encontrar esse usuário no Roblox.\nPor favor, tente novamente.",
                    color=EMBED_COLOR
                )
                await interaction.followup.send(embed=embed)
                return
            
            avatar_url = get_roblox_avatar_url(user_id)
            if not avatar_url:
                avatar_url = "https://cdn.discordapp.com/emojis/1128606053013176370.webp"
            
            embed = Embed(
                title=f"{EMOJIS['success']} Usuário Encontrado!",
                description=f"Este é o usuário **{username}** do Roblox?\n\n"
                           "Confirme abaixo para prosseguir com o pagamento:",
                color=EMBED_COLOR
            )
            embed.set_thumbnail(url=avatar_url)
            embed.set_image(url=avatar_url)
            
            view = ConfirmarUsuarioView(self.interaction, username, self.quantidade, self.preco_por_1000)
            await interaction.followup.send(embed=embed, view=view)
            await msg.delete()
            
        except asyncio.TimeoutError:
            embed = Embed(
                title=f"{EMOJIS['error']} Tempo Esgotado",
                description="Você demorou muito para responder.\nPor favor, inicie novamente o processo.",
                color=EMBED_COLOR
            )
            await interaction.followup.send(embed=embed)

    async def processar_pagamento(self, interaction: discord.Interaction):
        valor_total = (self.quantidade / 1000) * self.preco_por_1000
        payload_pix = gerar_payload_pix(CHAVE_PIX, f"{valor_total:.2f}", "Bernardo", "Rio de Janeiro")
        
        if not payload_pix:
            embed = Embed(
                title=f"{EMOJIS['error']} Erro no Pagamento",
                description="Não foi possível gerar o código PIX.\nPor favor, tente novamente mais tarde.",
                color=EMBED_COLOR
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = Embed(
            title=f"{EMOJIS['money']} PAGAMENTO VIA PIX",
            description=f"**Valor total:** R$ {valor_total:.2f}\n\n"
                       f"**📌 Instruções:**\n"
                       f"1. Abra seu app de pagamentos\n"
                       f"2. Escolha pagar via PIX\n"
                       f"3. Escolha 'PIX Copia e Cola'\n"
                       f"4. Cole o código abaixo\n\n"
                       f"**⏳ Tempo limite:** 30 minutos",
            color=EMBED_COLOR
        )
        embed.add_field(name="📋 Código PIX:", value=f"```{payload_pix}```", inline=False)
        embed.set_footer(text="Após o pagamento, aguarde a confirmação!")
        
        view = PagamentoView(self.interaction, self.username, self.quantidade, payload_pix, self.preco_por_1000)
        await interaction.followup.send(embed=embed, view=view)

class PagamentoView(BaseView):
    def __init__(self, interaction, username, quantidade, payload_pix, preco_por_1000):
        super().__init__()
        self.interaction = interaction
        self.username = username
        self.quantidade = quantidade
        self.payload_pix = payload_pix
        self.preco_por_1000 = preco_por_1000
        
        self.add_item(Button(emoji="📋", label="Copiar PIX", style=discord.ButtonStyle.blurple, custom_id="copiar", row=0))
        self.add_item(Button(emoji="❌", label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))
        self.add_item(Button(emoji=EMOJIS['success'], label="Marcar como Entregue", style=discord.ButtonStyle.success, custom_id="entregue", row=1))

    async def interaction_check(self, interaction: discord.Interaction):
        try:
            if interaction.data["custom_id"] == "copiar":
                await interaction.response.send_message(f"📋 **Código PIX copiado!**\n```{self.payload_pix}```", ephemeral=True)
            elif interaction.data["custom_id"] == "cancelar":
                await confirmar_cancelamento(interaction)
            elif interaction.data["custom_id"] == "entregue":
                await self.marcar_entregue(interaction)
        except Exception as e:
            print(f"{EMOJIS['error']} Erro no pagamento: {e}")

    async def marcar_entregue(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(f"{EMOJIS['error']} **Erro:** Apenas administradores podem marcar como entregue!", ephemeral=True)
            return
        
        comprador = interaction.guild.get_member(self.interaction.user.id)
        if comprador:
            embed = Embed(
                title=f"{EMOJIS['success']} COMPRA FINALIZADA!",
                description=f"{comprador.mention}, sua compra foi concluída com sucesso!\n\n"
                           f"**📌 Detalhes:**\n"
                           f"🔹 **Usuário Roblox:** {self.username}\n"
                           f"🔹 **Quantidade:** {self.quantidade} Robux\n"
                           f"🔹 **Valor Total:** R$ {(self.quantidade/1000)*self.preco_por_1000:.2f}\n"
                           f"🔹 **Entregue por:** {interaction.user.mention}",
                color=EMBED_COLOR
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1128606053013176370.webp")
            
            try:
                await comprador.send(embed=embed)
            except:
                pass
        
        # Enviar para webhook
        embed_webhook = Embed(
            title=f"{EMOJIS['money']} COMPRA CONCLUÍDA",
            description=f"Uma compra foi finalizada por {interaction.user.mention}",
            color=EMBED_COLOR
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
        
        await interaction.response.send_message(f"{EMOJIS['success']} **Compra marcada como entregue com sucesso!**", ephemeral=True)

# Funções principais
async def send_painel_atendimento(channel, metodo_compra):
    gamepass_msg = f"{EMOJIS['money']} **Gamepass sem taxa** - R$35/1k\n{EMOJIS['money']} **Gamepass com taxa** - R$45/1k"
    grupo_msg = f"{EMOJIS['money']} **Apenas com taxa** - R$45/1k"
    
    embed = Embed(
        title=f"{EMOJIS['cart']} Método de Compra - {'Gamepass' if metodo_compra == 'gamepass' else 'Grupo'}",
        description=f"Selecione como deseja comprar seus Robux:\n\n{gamepass_msg if metodo_compra == 'gamepass' else grupo_msg}",
        color=EMBED_COLOR
    )
    embed.set_footer(text="Clique nos botões abaixo para selecionar")
    await channel.send(embed=embed, view=PainelAtendimentoView(metodo_compra))

async def send_carrinho_embed(interaction: discord.Interaction, preco_por_1000):
    embed = Embed(
        title=f"{EMOJIS['cart']} Seu Carrinho de Compras",
        description="Informe **quantos Robux** você deseja comprar:\n\n"
                   f"**💵 Preço por 1.000 Robux:** R$ {preco_por_1000:.2f}",
        color=EMBED_COLOR
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
        embed.description = f"{EMOJIS['success']} Quantidade definida para **{quantidade} Robux**\n\n**💵 Preço por 1.000 Robux:** R$ {preco_por_1000:.2f}"
        
        view.quantidade = quantidade
        await view.original_message.edit(embed=embed, view=view)
        await msg.delete()
        
    except ValueError:
        embed = Embed(
            title=f"{EMOJIS['error']} Valor Inválido",
            description="Por favor, digite **apenas números**!\nExemplo: `5000` para 5.000 Robux",
            color=EMBED_COLOR
        )
        await interaction.followup.send(embed=embed, delete_after=10)
    except Exception as e:
        embed = Embed(
            title=f"{EMOJIS['error']} Erro Inesperado",
            description=f"Ocorreu um erro: {str(e)}",
            color=EMBED_COLOR
        )
        await interaction.followup.send(embed=embed, delete_after=10)

# Comandos
@bot.command()
@commands.has_permissions(administrator=True)
async def set(ctx):
    embed = Embed(
        title=f"{EMOJIS['loading']} PAINEL DE COMPRAS - FAPY STORE",
        description="Selecione abaixo como deseja comprar seus Robux:\n\n"
                   f"{EMOJIS['gamepass']} **Via Gamepass** (Com ou sem taxa)\n"
                   f"{EMOJIS['group']} **Via Grupo** (Apenas com taxa)\n\n"
                   f"{EMOJIS['cart']} Clique no menu abaixo para começar!",
        color=EMBED_COLOR
    )
    embed.set_image(url=BANNERS["payment"])
    await ctx.send(embed=embed, view=PainelComprasView())

@bot.event
async def on_ready():
    print(f"{EMOJIS['success']} Bot conectado como {bot.user}")
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