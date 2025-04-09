import discord
from discord.ext import commands
from discord.ui import Button, View, Select
from discord import Embed
import requests
from dotenv import load_dotenv
import os
import asyncio

# Configuração
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

# Configuração de aparência
EMBED_COLOR = 0xffffff
EMOJIS = {
    "success": "<:checkmark_correto:1359653313230143710>",
    "error": "<:checkmark_errado:1359653335862350005>",
    "money": "<:robux:1359653325213270199>",
    "cart": "🛒",
    "loading": "<a:white:1359645236472844609>"
}

BANNERS = {
    "welcome": "https://cdn.discordapp.com/attachments/1340143464041414796/1359650076452061376/image.png",
    "payment": "https://cdn.discordapp.com/attachments/1340143464041414796/1353119422784737381/image.png"
}

# Funções auxiliares
async def criar_canal_privado(guild, user):
    try:
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
                overwrites[role] = discord.PermissionOverwrite(read_messages=True)

        return await categoria.create_text_channel(
            name=f"{EMOJIS['cart']}-{user.name}",
            overwrites=overwrites
        )
    except Exception:
        return None

async def confirmar_cancelamento(interaction):
    embed = Embed(
        title=f"{EMOJIS['error']} Confirmar Cancelamento",
        description="Tem certeza que deseja cancelar?",
        color=EMBED_COLOR
    )
    
    class ConfirmView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="✅ Sim", style=discord.ButtonStyle.danger)
        async def confirm(self, inter, button):
            if inter.user != interaction.user:
                return
            if interaction.user.id in carrinhos_abertos:
                await carrinhos_abertos[interaction.user.id].delete()
                del carrinhos_abertos[interaction.user.id]
            await inter.response.send_message(f"{EMOJIS['success']} Compra cancelada!", ephemeral=True)
            await interaction.message.delete()
        
        @discord.ui.button(label="❌ Não", style=discord.ButtonStyle.secondary)
        async def cancel(self, inter, button):
            if inter.user != interaction.user:
                return
            await inter.response.send_message(f"{EMOJIS['success']} Compra mantida!", ephemeral=True)
            await interaction.message.delete()
    
    await interaction.response.send_message(embed=embed, view=ConfirmView(), ephemeral=True)

# Views
class PainelComprasView(View):
    def __init__(self):
        super().__init__(timeout=None)
        select = Select(
            placeholder="Selecione o método",
            options=[
                discord.SelectOption(label="Gamepass", emoji="🎮", value="gamepass"),
                discord.SelectOption(label="Grupo", emoji="👥", value="grupo")
            ]
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction):
        metodo = interaction.data["values"][0]
        await interaction.response.defer()
        
        if interaction.user.id in carrinhos_abertos:
            await interaction.followup.send(
                f"{EMOJIS['error']} Você já tem um carrinho aberto!",
                ephemeral=True
            )
            return

        channel = await criar_canal_privado(interaction.guild, interaction.user)
        if not channel:
            await interaction.followup.send(
                f"{EMOJIS['error']} Erro ao criar carrinho!",
                ephemeral=True
            )
            return

        carrinhos_abertos[interaction.user.id] = channel
        
        embed = Embed(
            title=f"{EMOJIS['cart']} Carrinho Criado",
            description=f"Seu canal privado: {channel.mention}",
            color=EMBED_COLOR
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        welcome_embed = Embed(
            title=f"{EMOJIS['loading']} Bem-vindo ao seu carrinho!",
            color=EMBED_COLOR
        )
        welcome_embed.set_image(url=BANNERS["welcome"])
        await channel.send(embed=welcome_embed)
        await enviar_painel_atendimento(channel, metodo)

class PainelAtendimentoView(View):
    def __init__(self, metodo):
        super().__init__(timeout=None)
        self.metodo = metodo
        
        if metodo == "gamepass":
            self.add_item(Button(label="Com Taxa R$45", style=discord.ButtonStyle.red, custom_id="com_taxa", row=0))
            self.add_item(Button(label="Sem Taxa R$35", style=discord.ButtonStyle.green, custom_id="sem_taxa", row=0))
        self.add_item(Button(label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))

    async def interaction_check(self, interaction):
        if interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        else:
            preco = 45 if interaction.data["custom_id"] == "com_taxa" else 35
            await enviar_carrinho_embed(interaction, preco)

class CarrinhoView(View):
    def __init__(self, preco):
        super().__init__(timeout=None)
        self.preco = preco
        self.add_item(Button(label="Prosseguir", style=discord.ButtonStyle.primary, custom_id="prosseguir", row=0))
        self.add_item(Button(label="Cancelar", style=discord.ButtonStyle.danger, custom_id="cancelar", row=0))

    async def interaction_check(self, interaction):
        if interaction.data["custom_id"] == "cancelar":
            await confirmar_cancelamento(interaction)
        else:
            await self.processar_compra(interaction)

    async def processar_compra(self, interaction):
        embed = Embed(
            title=f"{EMOJIS['loading']} Digite seu usuário Roblox",
            color=EMBED_COLOR
        )
        await interaction.response.send_message(embed=embed)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for("message", timeout=60, check=check)
            username = msg.content
            
            # Verificação do usuário Roblox
            user_id = requests.post(
                'https://users.roblox.com/v1/usernames/users',
                json={'usernames': [username]},
                headers={'Content-Type': 'application/json'}
            ).json().get('data', [{}])[0].get('id')
            
            if not user_id:
                await interaction.followup.send(
                    embed=Embed(
                        title=f"{EMOJIS['error']} Usuário não encontrado",
                        description="Digite novamente:",
                        color=EMBED_COLOR
                    )
                )
                return
            
            avatar_url = f"https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds={user_id}&size=180x180&format=Png"
            
            confirm_view = View(timeout=None)
            confirm_view.add_item(Button(label="Confirmar", style=discord.ButtonStyle.success, custom_id="confirmar"))
            confirm_view.add_item(Button(label="Corrigir", style=discord.ButtonStyle.danger, custom_id="corrigir"))
            
            embed = Embed(
                title=f"{EMOJIS['success']} Confirmar Usuário",
                description=f"Usuário: {username}",
                color=EMBED_COLOR
            )
            embed.set_thumbnail(url=avatar_url)
            
            await interaction.followup.send(embed=embed, view=confirm_view)
            await msg.delete()
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                embed=Embed(
                    title=f"{EMOJIS['error']} Tempo esgotado",
                    color=EMBED_COLOR
                )
            )

# Comandos
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = Embed(
        title=f"{EMOJIS['cart']} Painel de Compras",
        color=EMBED_COLOR
    )
    embed.set_image(url=BANNERS["payment"])
    await ctx.send(embed=embed, view=PainelComprasView())

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

bot.run(TOKEN)