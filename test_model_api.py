#!/usr/bin/env python3
"""
独立测试大模型 API 调用脚本
用法:
    1. 设置环境变量:
       export OPENROUTER_API_KEY="your-api-key"
       export OPENROUTER_MODEL="your-model-name"
       export OPENROUTER_BASE_URL="https://your-api-base-url/v1"
    2. 运行:
       python test_model_api.py
"""

import os
import asyncio
from openai import AsyncOpenAI
import json


async def test_openai_compatible_api():
    """测试 OpenAI 兼容格式的 API 调用"""
    
    # 从环境变量读取配置
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("OPENROUTER_MODEL", "z-ai/glm-4.7")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    print("="*80)
    print("测试配置:")
    print(f"  base_url: {base_url}")
    print(f"  model: {model}")
    print(f"  api_key: {'*'*(len(api_key)-8)}{api_key[-8:] if api_key else '(empty)'}")
    print(f"  api_key length: {len(api_key)}")
    print("="*80 + "\n")
    
    if not api_key:
        print("错误: OPENROUTER_API_KEY 环境变量未设置")
        print("请先运行: export OPENROUTER_API_KEY=your-api-key")
        return False
    
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        
        messages = [
            {
                "role": "user",
                "content": "你好，请介绍一下你自己，回答控制在100字以内。"
            }
        ]
        
        print(f"发送请求...")
        print(f"请求内容: {json.dumps(messages, indent=2, ensure_ascii=False)}")
        print()
        
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=500,
        )
        
        print("="*80)
        print("请求成功!")
        print(f"模型: {response.model}")
        if hasattr(response, 'model_dump'):
            print(f"完整响应: {json.dumps(response.model_dump(), indent=2, ensure_ascii=False)}")
        elif hasattr(response, '__dict__'):
            print(f"完整响应: {json.dumps(response.__dict__, indent=2, ensure_ascii=False, default=str)}")
        print(f"返回内容:")
        print("-"*80)
        if response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            print(content)
            print("-"*80)
            print(f"finish_reason: {response.choices[0].finish_reason}")
        if response.usage:
            print(f"token 使用: {response.usage}")
        print("="*80)
        return True
        
    except Exception as e:
        print("\n" + "="*80)
        print("请求失败!")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        
        # 尝试获取更详细的错误信息
        if hasattr(e, 'response'):
            try:
                err_response = getattr(e, 'response')
                print(f"\n响应状态码: {err_response.status_code}")
                print(f"响应头: {dict(err_response.headers)}")
                try:
                    content = err_response.json()
                    print(f"响应内容: {json.dumps(content, indent=2, ensure_ascii=False)}")
                except:
                    content_text = err_response.text
                    print(f"响应内容: {content_text}")
            except Exception as de:
                print(f"读取错误响应详情失败: {de}")
        
        print("\n详细堆栈:")
        import traceback
        traceback.print_exc()
        print("="*80)
        return False


if __name__ == "__main__":
    success = asyncio.run(test_openai_compatible_api())
    exit(0 if success else 1)
