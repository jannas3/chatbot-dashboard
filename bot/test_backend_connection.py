#!/usr/bin/env python3
"""
Script para testar a conexão com o backend
"""
import os
import sys
from dotenv import load_dotenv
import requests

load_dotenv()

def test_backend_connection():
    backend_url = os.getenv("BACKEND_URL", "http://localhost:4000/api/screenings")
    bot_secret = os.getenv("BOT_SHARED_SECRET", "dev_secret")
    
    print("=" * 60)
    print("TESTE DE CONEXÃO COM BACKEND")
    print("=" * 60)
    print(f"URL: {backend_url}")
    print(f"Secret: {bot_secret[:4]}..." if len(bot_secret) > 4 else f"Secret: {bot_secret}")
    print()
    
    # Teste 1: Health check
    try:
        health_url = backend_url.replace("/api/screenings", "/health")
        print(f"1. Testando health check: {health_url}")
        response = requests.get(health_url, timeout=5)
        if response.ok:
            print(f"   ✅ Backend está respondendo (status: {response.status_code})")
        else:
            print(f"   ⚠️  Backend respondeu com status: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"   ❌ ERRO: Não foi possível conectar ao backend em {health_url}")
        print(f"   Verifique se o backend está rodando na porta 4000")
        return False
    except Exception as e:
        print(f"   ❌ ERRO: {e}")
        return False
    
    print()
    
    # Teste 2: Teste de autenticação
    print("2. Testando autenticação do bot...")
    test_payload = {
        "nome": "Teste Conexão",
        "idade": 20,
        "matricula": "TEST999",
        "curso": "Teste",
        "periodo": "1",
        "phq9_respostas": [0, 1, 2, 0, 1, 2, 0, 1, 2],
        "gad7_respostas": [0, 1, 2, 0, 1, 2, 0],
        "phq9_score": 9,
        "gad7_score": 6,
        "disponibilidade": "Segunda 14h",
        "relatorio": "Teste de conexão do bot",
        "analise_ia": {
            "nivel_urgencia": "baixa",
            "fatores_protecao": ["teste"],
            "sinais_depressao": [],
            "sinais_ansiedade": [],
            "impacto_funcional": []
        },
        "telegram_id": "test_123"
    }
    
    try:
        response = requests.post(
            backend_url,
            json=test_payload,
            headers={
                "Content-Type": "application/json",
                "X-Bot-Secret": bot_secret,
            },
            timeout=10,
        )
        
        print(f"   Status Code: {response.status_code}")
        
        if response.ok:
            print("   ✅ Autenticação e validação OK!")
            result = response.json()
            print(f"   Triagem criada com ID: {result.get('id', 'N/A')}")
            return True
        else:
            print(f"   ❌ ERRO: Backend retornou status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Detalhes do erro:")
                print(f"   {error_data}")
            except:
                print(f"   Resposta: {response.text[:200]}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"   ❌ ERRO: Não foi possível conectar ao backend")
        print(f"   Verifique se o backend está rodando")
        return False
    except Exception as e:
        print(f"   ❌ ERRO: {e}")
        return False

if __name__ == "__main__":
    success = test_backend_connection()
    print()
    print("=" * 60)
    if success:
        print("✅ TESTE CONCLUÍDO COM SUCESSO")
        print("O bot deve conseguir enviar dados para o backend.")
    else:
        print("❌ TESTE FALHOU")
        print("Verifique:")
        print("1. Se o backend está rodando (porta 4000)")
        print("2. Se BOT_SHARED_SECRET está configurado corretamente")
        print("3. Se BACKEND_URL está correto")
        print("4. Se há firewall bloqueando a conexão")
    print("=" * 60)
    sys.exit(0 if success else 1)






