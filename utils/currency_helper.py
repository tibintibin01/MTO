def amount_to_words(amount):
    """
    Converts a numeric amount to a professional Philippine Peso word format.
    Example: 8322.63 -> "Eight Thousand Three Hundred Twenty Two & 63/100 Pesos Only"
    """
    try:
        amount = float(amount)
        if amount == 0:
            return "Zero Pesos Only"
            
        units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
        teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        thousands = ["", "Thousand", "Million", "Billion"]

        def _convert_chunk(n):
            res = ""
            h = n // 100
            t = n % 100
            if h > 0:
                res += units[h] + " Hundred "
            if t >= 10 and t < 20:
                res += teens[t-10] + " "
            else:
                if t // 10 > 0:
                    res += tens[t // 10] + " "
                if t % 10 > 0:
                    res += units[t % 10] + " "
            return res

        # Split pesos and centavos
        pesos = int(amount)
        centavos = int(round((amount - pesos) * 100))
        
        words = ""
        chunk_idx = 0
        while pesos > 0:
            chunk = pesos % 1000
            if chunk > 0:
                words = _convert_chunk(chunk) + thousands[chunk_idx] + " " + words
            pesos //= 1000
            chunk_idx += 1

        words = words.strip()
        if centavos > 0:
            words += f" & {centavos:02d}/100 Pesos Only"
        else:
            words += " Pesos Only"
            
        return words
    except:
        return "__________________________________________________"
