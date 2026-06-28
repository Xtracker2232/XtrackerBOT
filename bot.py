import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import aiohttp
import io
from datetime import datetime, date
import os
from dotenv import load_dotenv

# CHARGER LES VARIABLES D'ENVIRONNEMENT
load_dotenv()

# RÉCUPÉRER LES TOKENS
TOKEN = os.getenv('DISCORD_TOKEN')
BRIX_KEY = os.getenv('BRIX_KEY')
API_URL = os.getenv('API_URL', "https://www.xtracker.digital")
BRIX_API_URL = os.getenv('BRIX_API_URL', "https://api.brixhub.cc/api/v1")

if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN non défini !")
if not BRIX_KEY:
    raise ValueError("❌ BRIX_KEY non défini !")

# CONFIGURATION
FREE_PER_DAY = 5
MAX_RESULTS = 10
PANEL_COLOR = 0x6366f1
LOGO_URL = "https://cdn.discordapp.com/attachments/1477415267452719208/1507796087233056948/image.png?ex=6a415888&is=6a400708&hm=6fa068bf70c72520867efc4bbdc2a3d9c86557ef0c77aa7ebe49eff3b5673d66&"
TICKET_CATEGORY_ID = 1507494344079179977
TICKET_LOG_CHANNEL = 1507493165551059035

# RÔLES
ADMIN_ROLE_ID = 1493268066664976565
SUPPORT_ROLE_ID = 1493268041851474100
MEMBER_ROLE_ID = 1493268079877165208

# INTENTS
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# STATS
daily_usage = {}
bot_stats = {"searches": 0, "users": set()}

# ─── FONCTIONS DE VÉRIFICATION DES RÔLES ───────────────────────────────

def has_admin_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if not role:
        return False
    return role in interaction.user.roles

def has_support_role(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if admin_role and admin_role in interaction.user.roles:
        return True
    support_role = interaction.guild.get_role(SUPPORT_ROLE_ID)
    if support_role and support_role in interaction.user.roles:
        return True
    return False

def is_ticket_channel(channel) -> bool:
    return channel.name.startswith("ticket-")

# ─── FONCTIONS UTILITAIRES ───────────────────────────────────────────────

def get_remaining(uid):
    today = str(date.today())
    e = daily_usage.get(uid)
    if not e or e["date"] != today:
        return FREE_PER_DAY
    return max(0, FREE_PER_DAY - e["count"])

def use_search(uid):
    today = str(date.today())
    e = daily_usage.get(uid)
    if not e or e["date"] != today:
        daily_usage[uid] = {"date": today, "count": 1}
    else:
        daily_usage[uid]["count"] += 1
    bot_stats["searches"] += 1
    bot_stats["users"].add(uid)

# ─── API BRIX ─────────────────────────────────────────────────────────────

async def brix_search(payload):
    headers = {
        "X-API-Key": BRIX_KEY,
        "Content-Type": "application/json",
        "User-Agent": "Xtracker-Bot/1.0"
    }
    url = f"{BRIX_API_URL}/search"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as r:
            return r.status, await r.json()

async def brix_lookup(value):
    headers = {"X-API-Key": BRIX_KEY, "User-Agent": "Xtracker-Bot/1.0"}
    if "@" in value:
        path = f"email/{value}"
    elif value.upper().startswith("FR") and len(value) > 15:
        path = f"iban/{value}"
    else:
        path = f"phone/{value}"
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BRIX_API_URL}/lookup/{path}", headers=headers) as r:
            return r.status, await r.json()

async def get_site_stats():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}/api/admin/stats") as r:
                if r.status == 200:
                    return await r.json()
    except:
        pass
    return None

# ─── FORMATAGE ────────────────────────────────────────────────────────────

LABELS = {
    "nom_famille": "Nom", "prenom": "Prénom", "nom_naissance": "Nom naissance",
    "nom_affichage": "Nom affiché", "nom_utilisateur": "Utilisateur",
    "genre": "Genre", "civilite": "Civilité",
    "date_naissance": "Naissance", "annee_naissance": "Année naiss.",
    "ville_naissance": "Ville naiss.", "lieu_naissance": "Lieu naiss.",
    "email": "Email", "telephone": "Téléphone", "mobile": "Mobile", "adresse_ip": "IP",
    "adresse": "Adresse", "complement_adresse": "Complément",
    "code_postal": "Code postal", "ville": "Ville",
    "pays": "Pays", "region": "Région", "departement": "Département",
    "nir": "NIR (Sécu)", "iban": "IBAN", "bic": "BIC",
    "siret": "SIRET", "siren": "SIREN",
    "vin_plaque": "VIN/Plaque", "immatriculation": "Immat.",
    "marque": "Marque", "modele": "Modèle",
    "societe": "Société", "profession": "Profession", "fonction": "Fonction",
}

def format_profile(p, index, total):
    name = " ".join(filter(None, [p.get("prenom", ""), p.get("nom_famille", "")])) or "Profil inconnu"
    lines = []
    for k, label in LABELS.items():
        v = p.get(k)
        if v and str(v).strip() and str(v) != "undefined":
            lines.append(f"**{label}** : {v}")
    sources = " · ".join(p.get("_sources", [])) or "—"
    e = discord.Embed(
        title=f"👤 {name}",
        description="\n".join(lines) or "Aucune donnée disponible",
        color=PANEL_COLOR
    )
    e.add_field(name="📂 Sources", value=sources, inline=False)
    e.set_footer(text=f"Fiche {index + 1} / {total} · Xtracker CSINT")
    return e

def results_to_txt(results, query_info=""):
    lines = ["=" * 50, "XTRACKER — Résultats de recherche", "=" * 50, ""]
    if query_info:
        lines += [f"Recherche : {query_info}", ""]
    for i, p in enumerate(results):
        name = " ".join(filter(None, [p.get("prenom", ""), p.get("nom_famille", "")])) or "Profil inconnu"
        lines += [f"── Profil {i+1} : {name} ──"]
        for k, label in LABELS.items():
            v = p.get(k)
            if v and str(v).strip():
                lines.append(f"  {label} : {v}")
        sources = ", ".join(p.get("_sources", [])) or "—"
        lines += [f"  Sources : {sources}", ""]
    lines += ["=" * 50, f"Total : {len(results)} profil(s)", "=" * 50]
    return "\n".join(lines)

# ─── VIEW RÉSULTATS ───────────────────────────────────────────────────────

class ResultsView(View):
    def __init__(self, results, total, took, remaining, query_info=""):
        super().__init__(timeout=300)
        self.results = results[:MAX_RESULTS]
        self.total = total
        self.took = took
        self.remaining = remaining
        self.query_info = query_info
        self.index = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.results) - 1
        self.counter_btn.label = f"{self.index + 1} / {len(self.results)}"

    def current_embed(self):
        return format_profile(self.results[self.index], self.index, len(self.results))

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="counter_btn")
    async def counter_btn(self, interaction: discord.Interaction, button: Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="📥 Télécharger .txt", style=discord.ButtonStyle.success, custom_id="download_btn")
    async def download_btn(self, interaction: discord.Interaction, button: Button):
        txt = results_to_txt(self.results, self.query_info)
        f = discord.File(io.BytesIO(txt.encode("utf-8")), filename="xtracker_resultats.txt")
        await interaction.response.send_message(
            content="📥 Voici vos résultats en `.txt` :",
            file=f,
            ephemeral=True
        )

    @discord.ui.button(label="❌ Fermer", style=discord.ButtonStyle.danger, custom_id="close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="✅ Résultats fermés", color=0x22c55e),
            view=None
        )

# ─── MODALS ───────────────────────────────────────────────────────────────

class SearchModal(Modal, title="🔍 Recherche Xtracker"):
    nom = TextInput(label="Nom de famille", placeholder="Dupont", required=False)
    prenom = TextInput(label="Prénom", placeholder="Jean", required=False)
    email = TextInput(label="Email", placeholder="jean@gmail.com", required=False)
    telephone = TextInput(label="Téléphone", placeholder="0612345678", required=False)
    ville = TextInput(label="Ville", placeholder="Paris", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = interaction.user.id
        
        if get_remaining(uid) <= 0:
            e = discord.Embed(
                title="⏳ Limite atteinte",
                description=f"Vous avez utilisé vos **{FREE_PER_DAY} recherches** d'aujourd'hui.\nRevenez demain ou achetez des crédits sur [xtracker.digital](https://www.xtracker.digital).",
                color=0xef4444
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        payload = {"flexible": True, "per_page": MAX_RESULTS}
        query_parts = []
        
        if str(self.nom).strip():
            payload["nom_famille"] = str(self.nom).strip()
            query_parts.append(str(self.nom).strip())
        if str(self.prenom).strip():
            payload["prenom"] = str(self.prenom).strip()
            query_parts.append(str(self.prenom).strip())
        if str(self.email).strip():
            payload["email"] = str(self.email).strip()
            query_parts.append(str(self.email).strip())
        if str(self.telephone).strip():
            payload["telephone"] = str(self.telephone).strip()
            query_parts.append(str(self.telephone).strip())
        if str(self.ville).strip():
            payload["ville"] = str(self.ville).strip()
            query_parts.append(str(self.ville).strip())
        
        if not query_parts:
            e = discord.Embed(title="❌ Champs vides", description="Remplissez au moins un champ.", color=0xef4444)
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        status, data = await brix_search(payload)
        
        if status != 200:
            e = discord.Embed(title="❌ Erreur API", description=f"Code {status} — réessayez dans quelques instants.", color=0xef4444)
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        results = data.get("data", {}).get("results", [])
        total = data.get("meta", {}).get("total", 0)
        took = data.get("meta", {}).get("took_ms", 0)
        
        use_search(uid)
        remaining = get_remaining(uid)
        
        if not results:
            e = discord.Embed(title="😶 Aucun résultat", description="Essayez avec moins de critères ou une orthographe différente.", color=0xf59e0b)
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        query_info = " · ".join(query_parts)
        view = ResultsView(results, total, took, remaining, query_info)
        
        header = discord.Embed(
            title=f"🔍 {total:,} résultat{'s' if total > 1 else ''} · {took}ms",
            description=f"Affichage de **{min(len(results), MAX_RESULTS)}** fiches · 🎁 {remaining}/{FREE_PER_DAY} restantes\nUtilisez ◀ ▶ pour naviguer · 📥 pour télécharger",
            color=PANEL_COLOR
        )
        
        await interaction.followup.send(embed=header, ephemeral=True)
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

class LookupModal(Modal, title="⚡ Lookup rapide"):
    value = TextInput(label="Email, téléphone ou IBAN", placeholder="jean@gmail.com / 0612345678 / FR76...")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = interaction.user.id
        
        if get_remaining(uid) <= 0:
            e = discord.Embed(
                title="⏳ Limite atteinte",
                description=f"**{FREE_PER_DAY} recherches/jour** — revenez demain.",
                color=0xef4444
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        status, data = await brix_lookup(str(self.value).strip())
        
        if status != 200:
            e = discord.Embed(title="❌ Erreur API", description=f"Code {status} — réessayez.", color=0xef4444)
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        results = data.get("data", {}).get("results", [])
        total = data.get("meta", {}).get("total", 0)
        took = data.get("meta", {}).get("took_ms", 0)
        
        use_search(uid)
        remaining = get_remaining(uid)
        
        if not results:
            e = discord.Embed(title="😶 Aucun résultat", color=0xf59e0b)
            await interaction.followup.send(embed=e, ephemeral=True)
            return
        
        query_info = str(self.value).strip()
        view = ResultsView(results, total, took, remaining, query_info)
        
        header = discord.Embed(
            title=f"⚡ {total:,} résultat{'s' if total > 1 else ''} · {took}ms",
            description=f"Affichage de **{min(len(results), MAX_RESULTS)}** fiches\nUtilisez ◀ ▶ pour naviguer",
            color=PANEL_COLOR
        )
        
        await interaction.followup.send(embed=header, ephemeral=True)
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

# ─── MAIN VIEW (PERSISTANTE) ────────────────────────────────────────────

class MainView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(
            label="🌐 Site web",
            style=discord.ButtonStyle.link,
            url="https://www.xtracker.digital",
            row=1
        ))

    @discord.ui.button(label="🔍 Rechercher", style=discord.ButtonStyle.primary, custom_id="main_search", row=0)
    async def search(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SearchModal())

    @discord.ui.button(label="⚡ Lookup rapide", style=discord.ButtonStyle.secondary, custom_id="main_lookup", row=0)
    async def lookup(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(LookupModal())

    @discord.ui.button(label="🎁 Mes recherches", style=discord.ButtonStyle.secondary, custom_id="main_remaining", row=0)
    async def remaining(self, interaction: discord.Interaction, button: Button):
        r = get_remaining(interaction.user.id)
        e = discord.Embed(
            title="🎁 Vos recherches gratuites",
            description=f"Il vous reste **{r}/{FREE_PER_DAY}** recherches aujourd'hui.\nReset à minuit UTC.",
            color=PANEL_COLOR
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="💰 Tarifs", style=discord.ButtonStyle.secondary, custom_id="main_pricing", row=1)
    async def pricing(self, interaction: discord.Interaction, button: Button):
        e = discord.Embed(title="💰 Tarifs Xtracker", color=PANEL_COLOR)
        e.set_thumbnail(url=LOGO_URL)
        e.add_field(name="🎁 Gratuit via Bot", value=f"**{FREE_PER_DAY} recherches/jour** sans inscription", inline=False)
        e.add_field(name="⚡ Starter — 5€", value="**20 crédits** · 0.25€ / recherche", inline=False)
        e.add_field(name="🚀 Pro — 14.99€", value="**200 crédits** · 0.07€ / recherche", inline=False)
        e.add_field(name="👑 Enterprise — 49.99€", value="**1000 crédits** · 0.05€ / recherche", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

# ─── TICKET SYSTEM ────────────────────────────────────────────────────────

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        
        existing = discord.utils.get(guild.channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing:
            await interaction.response.send_message(f"❌ Vous avez déjà un ticket ouvert : {existing.mention}", ephemeral=True)
            return
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        
        admin_role = guild.get_role(ADMIN_ROLE_ID)
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            await interaction.response.send_message("❌ Catégorie de tickets introuvable.", ephemeral=True)
            return
        
        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name.lower()}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket de {interaction.user} | ID: {interaction.user.id}"
        )
        
        ticket_embed = discord.Embed(
            title="🎫 Ticket ouvert",
            description=(
                f"Bienvenue {interaction.user.mention} !\n\n"
                "Expliquez votre problème ou votre demande, un membre de l'équipe vous répondra rapidement.\n\n"
                "**Raisons courantes :**\n"
                "- Problème avec votre compte\n"
                "- Question sur les crédits\n"
                "- Bug ou erreur\n"
                "- Demande de remboursement\n"
                "- Autre"
            ),
            color=PANEL_COLOR
        )
        ticket_embed.set_thumbnail(url=LOGO_URL)
        ticket_embed.set_footer(text="Xtracker Support · Cliquez sur Fermer pour clôturer le ticket")
        
        await channel.send(embed=ticket_embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ Votre ticket a été créé : {channel.mention}", ephemeral=True)
        
        log_channel = bot.get_channel(TICKET_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="🎫 Nouveau ticket",
                description=f"**Utilisateur :** {interaction.user.mention}\n**Salon :** {channel.mention}",
                color=0x22c55e,
                timestamp=datetime.utcnow()
            )
            log_embed.set_thumbnail(url=LOGO_URL)
            await log_channel.send(embed=log_embed)

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        if not has_support_role(interaction):
            await interaction.response.send_message("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            return
        
        import asyncio
        channel = interaction.channel
        
        embed = discord.Embed(
            title="🔒 Ticket fermé",
            description=f"Fermé par {interaction.user.mention}. Suppression dans 5 secondes.",
            color=0xef4444
        )
        embed.set_thumbnail(url=LOGO_URL)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        
        try:
            await channel.delete(reason="Ticket fermé")
        except Exception as ex:
            print(f"Erreur suppression salon: {ex}")

class RulesView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ J'accepte le règlement", style=discord.ButtonStyle.success, custom_id="accept_rules")
    async def accept_rules(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        role = guild.get_role(MEMBER_ROLE_ID)
        
        if not role:
            await interaction.response.send_message("❌ Rôle introuvable.", ephemeral=True)
            return
        
        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Tu as déjà accepté le règlement !", ephemeral=True)
            return
        
        try:
            await interaction.user.add_roles(role, reason="Règlement accepté")
            embed = discord.Embed(
                title="✅ Bienvenue !",
                description=f"Tu as accepté le règlement et obtenu le rôle {role.mention} !\nBonne utilisation de Xtracker.",
                color=0x22c55e
            )
            embed.set_thumbnail(url=LOGO_URL)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'attribuer ce rôle.", ephemeral=True)

# ─── COMMANDES DE TICKET ─────────────────────────────────────────────────

@bot.tree.command(name="add", description="Ajouter une personne au ticket")
async def add_to_ticket(interaction: discord.Interaction, membre: discord.Member):
    if not has_support_role(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    
    if not is_ticket_channel(interaction.channel):
        await interaction.response.send_message("❌ Cette commande n'est utilisable que dans un ticket.", ephemeral=True)
        return
    
    try:
        await interaction.channel.set_permissions(membre, read_messages=True, send_messages=True, attach_files=True)
        await interaction.response.send_message(f"✅ {membre.mention} a été ajouté au ticket.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

@bot.tree.command(name="delete", description="Retirer une personne du ticket")
async def delete_from_ticket(interaction: discord.Interaction, membre: discord.Member):
    if not has_support_role(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    
    if not is_ticket_channel(interaction.channel):
        await interaction.response.send_message("❌ Cette commande n'est utilisable que dans un ticket.", ephemeral=True)
        return
    
    try:
        await interaction.channel.set_permissions(membre, read_messages=False)
        await interaction.response.send_message(f"✅ {membre.mention} a été retiré du ticket.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

@bot.tree.command(name="rename", description="Renommer le ticket")
async def rename_ticket(interaction: discord.Interaction, nouveau_nom: str):
    if not has_support_role(interaction):
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    
    if not is_ticket_channel(interaction.channel):
        await interaction.response.send_message("❌ Cette commande n'est utilisable que dans un ticket.", ephemeral=True)
        return
    
    try:
        new_name = f"ticket-{nouveau_nom.lower().replace(' ', '-')}"
        await interaction.channel.edit(name=new_name)
        await interaction.response.send_message(f"✅ Ticket renommé en `{new_name}`.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)

# ─── COMMANDES SLASH ──────────────────────────────────────────────────────

@bot.tree.command(name="panel", description="Afficher le panel Xtracker")
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔍 Xtracker — Panel de recherche",
        description=(
            "**Le moteur de recherche #1 du CSINT**\n"
            "+11 milliards d'entrées · Résultats instantanés\n\n"
            f"🎁 **{get_remaining(interaction.user.id)}/{FREE_PER_DAY} recherches gratuites** disponibles aujourd'hui\n\n"
            "Utilisez les boutons ci-dessous pour lancer une recherche."
        ),
        color=PANEL_COLOR
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Xtracker · CSINT Tool")
    await interaction.response.send_message(embed=embed, view=MainView())

@bot.tree.command(name="stats", description="Afficher les statistiques Xtracker")
async def stats(interaction: discord.Interaction):
    if not has_admin_role(interaction):
        await interaction.response.send_message("❌ Permission refusée. Réservé aux administrateurs.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    site = await get_site_stats()
    
    embed = discord.Embed(
        title="📊 Statistiques Xtracker",
        color=PANEL_COLOR,
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=LOGO_URL)
    
    if site:
        embed.add_field(name="━━ 🌐 Site Web ━━", value="​", inline=False)
        embed.add_field(name="👥 Utilisateurs", value=f"**{site.get('total_users', '—'):,}**", inline=True)
        embed.add_field(name="🔍 Recherches total", value=f"**{site.get('total_searches', '—'):,}**", inline=True)
        embed.add_field(name="💰 Revenus", value=f"**{site.get('revenue_eur', 0):.2f}€**", inline=True)
        embed.add_field(name="🆕 Nouveaux aujourd'hui", value=f"**{site.get('new_today', 0)}**", inline=True)
        embed.add_field(name="🔎 Recherches aujourd'hui", value=f"**{site.get('searches_today', 0)}**", inline=True)
        embed.add_field(name="🚫 Comptes bannis", value=f"**{site.get('banned', 0)}**", inline=True)
    else:
        embed.add_field(name="🌐 Site Web", value="❌ Impossible de récupérer les stats", inline=False)
    
    embed.add_field(name="━━ 🤖 Bot Discord ━━", value="​", inline=False)
    embed.add_field(name="🔍 Recherches via bot", value=f"**{bot_stats['searches']:,}**", inline=True)
    embed.add_field(name="👤 Utilisateurs uniques", value=f"**{len(bot_stats['users']):,}**", inline=True)
    embed.add_field(name="📅 Depuis", value="**Démarrage du bot**", inline=True)
    
    today = str(date.today())
    active_today = sum(1 for v in daily_usage.values() if v.get("date") == today)
    searches_today = sum(v.get("count", 0) for v in daily_usage.values() if v.get("date") == today)
    embed.add_field(name="👥 Actifs aujourd'hui", value=f"**{active_today}**", inline=True)
    embed.add_field(name="🔍 Recherches aujourd'hui", value=f"**{searches_today}**", inline=True)
    embed.set_footer(text="Xtracker · Stats en temps réel")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="ticket", description="Envoyer le panel de tickets")
async def ticket_panel(interaction: discord.Interaction):
    if not has_support_role(interaction):
        await interaction.response.send_message("❌ Permission refusée. Réservé au staff.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 Support Xtracker",
        description="**Besoin d'aide ?**\n\nCliquez sur le bouton ci-dessous pour ouvrir un ticket.\nL'équipe vous répondra rapidement.\n\n**Avant d'ouvrir un ticket :**\n- Vérifiez le salon #faq\n- Lisez les règles\n- Un ticket = une demande",
        color=PANEL_COLOR
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Xtracker Support")
    await interaction.response.send_message(embed=embed, view=TicketView())

@bot.tree.command(name="reglement", description="Afficher le règlement avec bouton d'acceptation")
async def reglement(interaction: discord.Interaction):
    if not has_admin_role(interaction):
        await interaction.response.send_message("❌ Permission refusée. Réservé aux administrateurs.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📜 Règlement — Xtracker",
        description=(
            "En cliquant sur **J'accepte**, tu confirmes avoir lu et accepté les règles suivantes.\n\n"
            "**1.** Respecte tous les membres. Aucune insulte tolérée.\n"
            "**2.** Pas de spam ou flood dans les salons.\n"
            "**3.** Pas de pub sans autorisation d'un admin.\n"
            "**4.** Xtracker est un outil d'investigation. Interdiction de l'utiliser pour harcèlement ou menaces.\n"
            "**5.** Ne partage pas les résultats de recherches publiquement dans les salons.\n"
            "**6.** Tu es seul responsable de l'utilisation des données trouvées.\n"
            "**7.** Les crédits achetés ne sont pas remboursables sauf bug prouvé.\n"
            "**8.** Tout abus entraîne un ban immédiat du site et du Discord.\n"
            "**9.** Ne partage jamais tes identifiants de connexion.\n"
            "**10.** Les admins peuvent sanctionner tout comportement inapproprié.\n\n"
            "En acceptant ce règlement, tu confirmes avoir **+13 ans** et acceptes nos CGU disponibles sur [xtracker.digital](https://www.xtracker.digital/cgu.html)."
        ),
        color=PANEL_COLOR
    )
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text="Xtracker · Cliquez sur le bouton pour accéder au serveur")
    await interaction.response.send_message(embed=embed, view=RulesView())

# ─── ÉVÉNEMENTS ───────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    bot.add_view(MainView())
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(RulesView())
    
    await bot.tree.sync()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.playing, name="/panel | Xtracker")
    )
    print(f"✅ {bot.user} connecté sur {len(bot.guilds)} serveur(s)")
    print(f"✅ Rôle Admin: {ADMIN_ROLE_ID}")
    print(f"✅ Rôle Support: {SUPPORT_ROLE_ID}")
    print(f"✅ Rôle Membre: {MEMBER_ROLE_ID}")
    print(f"✅ Catégorie Tickets: {TICKET_CATEGORY_ID}")

# ─── LANCEMENT ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)