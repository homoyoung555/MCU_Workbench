using System;
using System.IO;
using System.Linq;
using System.Text;

namespace _Hex_To_Sram_Pat
{
    class PT067_Program
    {
        private const string StilPath = @"D:\01_Work\CP_Map_Change\Hex\";

        private const string StilPath_new = @"D:\01_Work\CP_Map_Change\Pat\";

        private const int SramStartAddr = 0x20000000;

        private const int WriteSize = 0x22000042;

        private const int ReadSize = 0x20000042;

        private const string InitialStr = " *11*;";

        static void Main(string[] args)
        {
            var root = new DirectoryInfo(StilPath);
            var files = root.GetFiles("*.hex");

            foreach (var file in files)
            {
                var fileName = Path.GetFileNameWithoutExtension(file.Name) + "_Sram";
                Console.WriteLine(fileName);

                if (Read(file.FullName, fileName))
                    Console.WriteLine("解析成功");
                else
                    Console.WriteLine("解析失败");
            }
            Console.ReadLine();
        }

        static bool Read(string pathSrc, string pathDet)
        {
            bool bSuccess = true;
            var sb = new StringBuilder();

            Pat_header(sb, pathDet);
            SWD_Check_Start(sb);

            SWD_Write_Addr(sb, 0xE000EDF0);
            SWD_Write_Fix(sb, WriteSize);
            SWD_Write_Data(sb, 0xA05F0003);

            var hexLines = File.ReadAllLines(pathSrc);
            foreach (var line in hexLines)
                Write_pat(sb, line);

            foreach (var line in hexLines)
                Read_pat(sb, line);

            Pat_end(sb);
            File.WriteAllText(StilPath_new + pathDet + ".pat", sb.ToString());
            return bSuccess;
        }

        static void Pat_header(StringBuilder sb, string txtName)
        {
            sb.AppendLine("SET_DEC_FILE  \"pin.dec\"");
            sb.AppendLine();
            sb.AppendLine("HEADER");
            sb.AppendLine("PA14,PA13,NRST;");
            sb.AppendLine($"SPM_PATTERN({txtName}) {{");
            sb.AppendLine();
            sb.AppendLine(" *011*TS1;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *111*RPT 700;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *111*;");
        }

        static void Pat_end(StringBuilder sb)
        {
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *101*RPT 53;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *011*STOP;");
            sb.AppendLine("}");
        }

        static void SWD_Check_Start(StringBuilder sb)
        {
            sb.AppendLine(" *111*RPT 2;");
            sb.AppendLine(" *101*RPT 2;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*RPT 2;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1H1*RPT 3;");
            sb.AppendLine(" *1L1*;");
            sb.AppendLine(" *1H1*RPT 3;");
            sb.AppendLine(" *1L1*RPT 3;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 3;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 5;");
            sb.AppendLine(" *1H1*RPT 4;");
            sb.AppendLine(" *1L1*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 5;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *101*RPT 52;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*RPT 2;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*RPT 29;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*RPT 55;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*RPT 3;");
            sb.AppendLine(" *111*RPT 2;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*RPT 87;");
        }

        static void SWD_Write_Addr(StringBuilder sb, long addr)
        {
            AppendSwdBitSequence(sb);
            AppendBinaryWithParity(sb, addr);
            sb.AppendLine(" *101*RPT 3;");
        }

        static void SWD_Write_Fix(StringBuilder sb, long addr)
        {
            AppendSwdBitSequenceFix(sb);
            AppendBinaryWithParity(sb, addr);
            sb.AppendLine(" *101*RPT 3;");
        }

        static void SWD_Write_Data(StringBuilder sb, long data)
        {
            sb.AppendLine(" *111*RPT 2;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*RPT 3;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*;");

            AppendBinaryWithParity(sb, data);
            sb.AppendLine(" *101*RPT 53;");
        }

        static void SWD_Read_Fix(StringBuilder sb, long addr)
        {
            AppendSwdBitSequenceFix(sb);
            AppendBinaryWithParity(sb, addr);
            sb.AppendLine(" *101*RPT 30;");

            sb.AppendLine(" *111*RPT 5;");
            sb.AppendLine(" *101*RPT 2;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1X1*RPT 35;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*RPT 2;");
        }

        static void SWD_Read_Data(StringBuilder sb, long data)
        {
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*RPT 4;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");

            var dataBits = Convert.ToString(data, 2).PadLeft(32, '0').ToCharArray();
            Array.Reverse(dataBits);
            var dataStr = new string(dataBits);
            dataStr = dataStr.Replace('1', 'H').Replace('0', 'L');

            int parityBit = (dataStr.Count(c => c == 'H') % 2 != 0) ? 1 : 0;
            sb.AppendLine(InitialStr.Insert(InitialStr.IndexOf('*') + 2, dataStr[0].ToString()) + $"//{data:X8}");

            for (int i = 1; i < dataStr.Length; i++)
                sb.AppendLine(InitialStr.Insert(InitialStr.IndexOf('*') + 2, dataStr[i].ToString()));

            sb.AppendLine($" *1{(parityBit == 1 ? 'H' : 'L')}1*;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*RPT 52;");
        }

        static void AppendSwdBitSequence(StringBuilder sb)
        {
            sb.AppendLine(" *111*RPT 2;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*RPT 3;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*;");
        }

        static void AppendSwdBitSequenceFix(StringBuilder sb)
        {
            sb.AppendLine(" *111*RPT 2;");
            sb.AppendLine(" *101*RPT 3;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *101*;");
            sb.AppendLine(" *111*;");
            sb.AppendLine(" *1H1*;");
            sb.AppendLine(" *1L1*RPT 2;");
            sb.AppendLine(" *1X1*;");
            sb.AppendLine(" *101*;");
        }

        static void AppendBinaryWithParity(StringBuilder sb, long value)
        {
            var bits = Convert.ToString(value, 2).PadLeft(32, '0').ToCharArray();
            Array.Reverse(bits);
            var bitStr = new string(bits);

            int parityBit = (bitStr.Count(c => c == '1') % 2 != 0) ? 1 : 0;
            sb.AppendLine(InitialStr.Insert(InitialStr.IndexOf('*') + 2, bitStr[0].ToString()) + $"//{value:X8}");

            for (int i = 1; i < bitStr.Length; i++)
                sb.AppendLine(InitialStr.Insert(InitialStr.IndexOf('*') + 2, bitStr[i].ToString()));

            sb.AppendLine($" *1{parityBit}1*;");
        }

        static void Write_pat(StringBuilder sb, string dataLine)
        {
            if (dataLine.Length < 9 || dataLine.Substring(7, 2) != "00")
                return;

            int addr = HexToInt32(dataLine.Substring(3, 4));
            int dataLength = HexToInt32(dataLine.Substring(1, 2));

            while (dataLength < 4)
            {
                dataLine = dataLine.Insert(dataLine.Length - 2, "00");
                dataLength++;
            }

            long writeData = 0;
            for (int j = 0; j < dataLength; j++)
            {
                int index = j % 4;
                writeData += HexToInt32(dataLine.Substring(9 + j * 2, 2)) * (1L << (index * 8));

                if (j % 4 == 0)
                {
                    SWD_Write_Addr(sb, addr + j + SramStartAddr);
                    SWD_Write_Fix(sb, WriteSize);
                }
                if ((j + 1) % 4 == 0)
                {
                    SWD_Write_Data(sb, writeData);
                    writeData = 0;
                }
            }
        }

        static void Read_pat(StringBuilder sb, string dataLine)
        {
            if (dataLine.Length < 9 || dataLine.Substring(7, 2) != "00")
                return;

            int addr = HexToInt32(dataLine.Substring(3, 4));
            int dataLength = HexToInt32(dataLine.Substring(1, 2));

            while (dataLength < 4)
            {
                dataLine = dataLine.Insert(dataLine.Length - 2, "00");
                dataLength++;
            }

            long readData = 0;
            for (int j = 0; j < dataLength; j++)
            {
                int index = j % 4;
                readData += HexToInt32(dataLine.Substring(9 + j * 2, 2)) * (1L << (index * 8));

                if (j % 4 == 0)
                {
                    SWD_Write_Addr(sb, addr + j + SramStartAddr);
                    SWD_Read_Fix(sb, ReadSize);
                }
                if ((j + 1) % 4 == 0)
                {
                    SWD_Read_Data(sb, readData);
                    readData = 0;
                }
            }
        }

        static int HexToInt32(string hex)
        {
            int result = 0;
            for (int i = 0; i < hex.Length; i++)
            {
                char c = hex[i];
                int value = c >= 'A' ? c - 'A' + 10 : c - '0';
                result = (result << 4) | value;
            }
            return result;
        }
    }
}
