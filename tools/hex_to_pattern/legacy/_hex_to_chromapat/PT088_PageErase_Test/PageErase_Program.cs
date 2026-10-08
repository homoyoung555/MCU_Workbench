using System;
using System.Linq;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace PT088_hex_to_chromapat
{
    class PT088_Program
    {
        //public static string StilPath = @"D:\\CP_Pattern\\Start\\";
        //public static string StilPath_new = @"D:\\CP_Pattern\\end\\";

        public static string StilPath = @"D:\\01_Work\\CP_Map_Change\\Hex\\";
        public static string StilPath_new = @"D:\\01_Work\\CP_Map_Change\\Pat\\";

        public static int cyc_count = 0;
        public static bool addr_first = true;
        public static int addr_end_num = 0;
        public static int Erase_delay = 17500;//T=0.2uS,Erase=3.5mS
        public static int Pgm_delay = 5000;//T=0.2uS,Pgm=1mS
        public static int PageSize = 256;
        public static int StartAddr = 0;
        public static int PageAddr = 0x20000;
        public static int Addroffset = 0;

        static void Main(string[] args)
        {

            DirectoryInfo root = new DirectoryInfo(StilPath);
            FileInfo[] thefileInfo = root.GetFiles("*.hex");

            foreach (FileInfo NextFile in thefileInfo)
            {
                cyc_count = 0;
                string strFileName = NextFile.Name.Substring(0, NextFile.Name.IndexOf(".hex"));//获取新生成的pat文件名
                Console.WriteLine(strFileName);
                if (Read(NextFile.FullName, strFileName))
                    Console.WriteLine("解析成功");
                else
                    Console.WriteLine("解析失败");

                addr_first = true;
                addr_end_num = 0;
            }
            Console.ReadLine();
        }

        static public bool Read(string pathSrc, string pathDet)
        {
            bool bSuccess = true;
            Addroffset = 0;
            StreamReader sr = new StreamReader(pathSrc, Encoding.Default);
            StreamWriter sw = new StreamWriter(StilPath_new + pathDet + ".pat");

            //SCLK,SDA,NRST
            string InitialStr = " *11*;";//初始字符串
            string line = "";


            Pat_header(sw, pathDet);

            Enter_Fbist_mode(sw);
            //Read_trim_mode(sw);//Read the data in flash special row to corresponding trim registers.PT088 close
            /*
            for (StartAddr = 0; StartAddr < PageAddr; StartAddr += PageSize)
            {
                Pre_program_test(sw, InitialStr);
                Bulk_erase_test(sw, InitialStr);
            }
            */

            
            //write
            while ((line = sr.ReadLine()) != null)
            {
                Write_pat(sw, line, InitialStr);

            }

            Console.WriteLine("Addroffset={0}",Addroffset);
            sr.Close();


            sr = new StreamReader(pathSrc, Encoding.Default);
            //read

            while ((line = sr.ReadLine()) != null)
            {
                //Read_pat(sw, line, InitialStr);

            }
            

            Pat_end(sw);
            sr.Close();
            sw.Close();
            return bSuccess;
        }

        static void Pat_header(StreamWriter sw, string TxtName)
        {
            string PatName = "SPM_PATTERN() {";
            PatName = PatName.Insert(PatName.IndexOf("(") + 1, TxtName);

            sw.WriteLine("SET_DEC_FILE  \"pin.dec\"");
            sw.WriteLine("");
            sw.WriteLine("HEADER");
            sw.WriteLine("PA5,PA4,PD13;");//SCLK,SDA,NRST
            sw.WriteLine(PatName);
            sw.WriteLine("");

            sw.WriteLine(" *011*TS1;");
            sw.WriteLine(" *011*;");
            sw.WriteLine(" *011*RPT 100;");
            sw.WriteLine(" *011*;");
            sw.WriteLine(" *111*;");
        }

        static void Pat_end(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *011*;");
            sw.WriteLine(" *XXX*STOP;");
            sw.WriteLine("}");
        }

        static void Enter_Fbist_mode(StreamWriter sw)
        {
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *110*;//0xB5");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;//0x94");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *110*;//0xD9");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *100*;");
            sw.WriteLine(" *110*;");

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");

        }


        static void Read_trim_mode(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 58;");
            sw.WriteLine(" *101*;");
        }

        static void Write_pagelatch(StreamWriter sw)
        {
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *111*;");

            sw.WriteLine(" *111*RPT 8;//ecc");
        }

        static void Tcy_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *1X1*;");
            //sw.WriteLine(" *0X0*;");
        }
        static void Ts1_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 80;");//>15us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts2p_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 30;");//>5us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Preprog_Delay_pt068(StreamWriter sw)
        {

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*RPT 1000;");//200us，T=200ns
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
        }

        static void Erase_Delay_pt068(StreamWriter sw)
        {

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS5;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*RPT " + Erase_delay.ToString() + ";");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *111*;");
        }

        static void Prog_Delay_pt068(StreamWriter sw)
        {

            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS6;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*RPT " + Pgm_delay.ToString() + ";");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");//sw.WriteLine(" *111*TS1;");
            sw.WriteLine(" *111*;");
        }

        static void Tps3_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 350;");//>60us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts3_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 30;");//>5us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Ts0_pt068(StreamWriter sw)
        {
            sw.WriteLine(" *110*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*RPT 40;");//>6us，T=200ns
            sw.WriteLine(" *101*;");
        }

        static void Pre_program_test(StreamWriter sw, String InitialStr)
        {
            //set 8b'0,ECC_ON,BANK_EN[1:0],LP_MUX_SEL,OP_MUX_SEL[1:0],BANK_SEL[1:0]
            Write_fbist_reg(sw, 0x24, 0x00A1, InitialStr);//addr,data,0x00A1=bank0,0x00C2=bank1

            //set 7b'0,RA[8:0]
            Write_fbist_reg(sw, 0x1E, StartAddr / PageSize, InitialStr);//addr,data

            //set 5b'0,AXA, CA[4:0], PA[4:0]
            Write_fbist_reg(sw, 0x1F, 0x0000, InitialStr);//addr,data

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data

            Tcy_pt068(sw);
            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=pre_pgm
            Write_fbist_reg(sw, 0x20, 0x0007, InitialStr);//addr,data

            Tcy_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=01,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x001C, InitialStr);
            Ts1_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x002C, InitialStr);
            Ts2p_pt068(sw);

            //set 9b'0,PE=1,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x006C, InitialStr);
            Preprog_Delay_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x002C, InitialStr);
            Tps3_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=11,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x003C, InitialStr);
            Ts3_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x000C, InitialStr);
            Ts0_pt068(sw);
        }
        static void Bulk_erase_test(StreamWriter sw, String InitialStr)
        {

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data
            Tcy_pt068(sw);

            //set 8b'0,ECC_ON,BANK_EN[1:0],LP_MUX_SEL,OP_MUX_SEL[1:0],BANK_SEL[1:0]
            Write_fbist_reg(sw, 0x24, 0x00A5, InitialStr);//addr,data,0x00A5=bank0,0x00C6=bank1

            //set 9b'0,PE=0,SEQ[1:0]=01,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0018, InitialStr);
            Ts1_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0028, InitialStr);
            Ts2p_pt068(sw);

            //set 9b'0,PE=1,SEQ[1:0]=10,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0068, InitialStr);
            Erase_Delay_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0028, InitialStr);
            Tps3_pt068(sw);

            // set 9b'0,PE=0,SEQ[1:0]=11,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0038, InitialStr);
            Ts3_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=Erase page
            Write_fbist_reg(sw, 0x20, 0x0008, InitialStr);
            Ts0_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data
            Tcy_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=clear page latches
            Write_fbist_reg(sw, 0x20, 0x0001, InitialStr);
            Tcy_pt068(sw);
        }

        static void Prog_addr_test(StreamWriter sw, String InitialStr, int addrLength)
        {
            //set 8b'0,ECC_ON,BANK_EN[1:0],LP_MUX_SEL,OP_MUX_SEL[1:0],BANK_SEL[1:0]
            Write_fbist_reg(sw, 0x24, 0x00CA, InitialStr);//addr,data,0x00A9=bank0,0x00CA=bank1

            //set 7b'0,RA[8:0]
            Write_fbist_reg(sw, 0x1E, addrLength / PageSize, InitialStr);//addr,data

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=clear page latches
            Write_fbist_reg(sw, 0x20, 0x0001, InitialStr);
            Tcy_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data
            Tcy_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=Write page latches
            Write_fbist_reg(sw, 0x20, 0x0006, InitialStr);//addr,data
            Tcy_pt068(sw);
        }

        static void Prog_PEdelay_test(StreamWriter sw, String InitialStr)
        {
            //set 9b'0,PE=0,SEQ[1:0]=01,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x001C, InitialStr);
            Ts1_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x002C, InitialStr);
            Ts2p_pt068(sw);

            //set 9b'0,PE=1,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x006C, InitialStr);
            Prog_Delay_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=10,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x002C, InitialStr);
            Tps3_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=11,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x003C, InitialStr);
            Ts3_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=Program page
            Write_fbist_reg(sw, 0x20, 0x000C, InitialStr);
            Ts0_pt068(sw);

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data
            Tcy_pt068(sw);

        }

        static void Read_addr_test(StreamWriter sw, String InitialStr, int addrLength)
        {
            //set 8b'0,ECC_ON,BANK_EN[1:0],LP_MUX_SEL,OP_MUX_SEL[1:0],BANK_SEL[1:0]
            Write_fbist_reg(sw, 0x24, 0x00A9, InitialStr);//addr,data

            //set 9b'0,PE=0,SEQ[1:0]=00,MODE[3:0]=nroma read
            Write_fbist_reg(sw, 0x20, 0x0005, InitialStr);//addr,data
            Tcy_pt068(sw);

            //set 7b'0,RA[8:0]
            Write_fbist_reg(sw, 0x1E, addrLength / PageSize, InitialStr);//addr,data

            //set 5b'0,AXA, CA[4:0], PA[4:0]
            Write_fbist_reg(sw, 0x1F, 0x0000, InitialStr);//addr,data

            //set read_mode=1 continue read
            Write_fbist_reg(sw, 0x21, 0x0800, InitialStr);
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *111*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *101*;");
            sw.WriteLine(" *1L1*;"); //dummy
            sw.WriteLine(" *1X1*RPT 8;//ecc");
        }


        static void Write_fbist_reg(StreamWriter sw, int addr, int data, String StartStr)
        {
            string AddrStr = Convert.ToString(addr, 2).PadLeft(7, '0');//将int类型的值转换为7bit长度的字符串
            //AddrStr = new string(AddrStr.ToCharArray().Reverse().ToArray());//倒转字符串
            string DataStr = Convert.ToString(data, 2).PadLeft(16, '0');
            //DataStr = new string(DataStr.ToCharArray().Reverse().ToArray());
            sw.WriteLine(" *1X0*;");
            sw.WriteLine(" *111*;");
            for (int i = 0; i < AddrStr.Length; i++)
            {
                sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, AddrStr.Substring(i, 1)));
            }
            for (int i = 0; i < DataStr.Length; i++)
            {
                sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));

                if (i == DataStr.Length - 1) sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*") + 2, DataStr.Substring(i, 1)));
            }

        }


        static void Write_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;
            if (DataStr.Substring(7, 2) == "00") effective_data = true;//hex 文件“00”表示数据有效
            if (DataStr == ":020000040001F9") Addroffset = 0x10000;

            if (effective_data)
            {
                int addrLength = AddrStr_to_int(DataStr.Substring(3, 4))+ Addroffset;//获取地址2Byte

                if (addrLength % PageSize == 0) Prog_addr_test(sw, InitialStr, addrLength);//每page写一次地址

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要写入数据的长度
                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }
                for (int j = 0; j < dataLength; j++)
                {
                    if (j % 8 == 0) Write_pagelatch(sw);//每次写2word(8Byte)前，先发write pagelatch命令

                    int index = (j / 8) * 8 + 7 - (j % 8);//每次写2word(8Byte)，高位先发
                    int writedata = DataStr_to_int(DataStr.Substring(9 + index * 2, 2));

                    string DataBinaryStr = Convert.ToString(writedata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串

                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", writedata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));

                        if ((j + 1) % 8 == 0 && i == DataBinaryStr.Length) sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));//每写8byte,最后1bit补一个周期
                    }

                    addr_end_num = addrLength + j + 1;
                }

                if (addr_end_num % PageSize == 0) Prog_PEdelay_test(sw, InitialStr);//每page delay一次

            }
            if (DataStr.Substring(7, 2) == "05" && (addr_end_num % PageSize != 0))
            {
                int dataLength = PageSize - (addr_end_num % PageSize);
                for (int j = 0; j < dataLength; j++)
                {
                    if (j % 8 == 0) Write_pagelatch(sw);//每次写2word(8Byte)前，先发write pagelatch命令

                    int index = (j / 8) * 8 + 7 - (j % 8);//每次写2word(8Byte)，高位先发
                    int writedata = 0xFF;

                    string DataBinaryStr = Convert.ToString(writedata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串

                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", writedata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));

                        if ((j + 1) % 8 == 0 && i == DataBinaryStr.Length) sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));//每写8byte,最后1bit补一个周期
                    }

                }

                Prog_PEdelay_test(sw, InitialStr);//end
            }

        }
        static void Read_pat(StreamWriter sw, String DataStr, String InitialStr)
        {
            bool effective_data = false;

            if (DataStr.Substring(7, 2) == "00") effective_data = true;//hex 文件“00”表示数据有效


            if (effective_data)
            {
                if (addr_first)
                {
                    int addrLength = AddrStr_to_int(DataStr.Substring(3, 4));//获取地址2Byte
                    if (addrLength % PageSize == 0) Read_addr_test(sw, InitialStr, addrLength);

                }

                int dataLength = DataStr_to_int(DataStr.Substring(1, 2));//需要读取数据的长度
                while (dataLength < 16)
                {
                    DataStr = DataStr.Insert(DataStr.Length - 2, "FF");
                    dataLength += 1;
                }
                for (int j = 0; j < dataLength; j++)
                {
                    if (j % 8 == 0 && addr_first == false) //每次读2word(8Byte)前，先发read命令
                    {
                        sw.WriteLine(" *111*;");
                        sw.WriteLine(" *1L1*;");
                        sw.WriteLine(" *1X1*RPT 8;//ecc");
                    }

                    int index = (j / 8) * 8 + 7 - (j % 8);//每次读1word(4Byte)，高位先发
                    int readdata = DataStr_to_int(DataStr.Substring(9 + index * 2, 2));

                    string DataBinaryStr = Convert.ToString(readdata, 2).PadLeft(8, '0');//将1byte数据转换为字符串
                    DataBinaryStr = new string(DataBinaryStr.ToCharArray().Reverse().ToArray());//倒转字符串
                    DataBinaryStr = DataBinaryStr.Replace('1', 'H');
                    DataBinaryStr = DataBinaryStr.Replace('0', 'L');
                    for (int i = 1; i <= DataBinaryStr.Length; i++)
                    {
                        if (i == 1)
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)) + "//" + string.Format("{0:x2}", readdata));
                        //sw.WriteLine(StartStr.Insert(StartStr.IndexOf("*")+2, DataBinaryStr.Substring(DataBinaryStr.Length - i , 1)));
                        else
                            sw.WriteLine(InitialStr.Insert(InitialStr.IndexOf("*") + 2, DataBinaryStr.Substring(DataBinaryStr.Length - i, 1)));
                    }
                    addr_first = false;
                }



            }
        }



        static public int AddrStr_to_int(string DataStr)
        {
            int bit0 = Convert.ToChar(DataStr.Substring(0, 1));
            int bit1 = Convert.ToChar(DataStr.Substring(1, 1));
            int bit2 = Convert.ToChar(DataStr.Substring(2, 1));
            int bit3 = Convert.ToChar(DataStr.Substring(3, 1));

            int length = 0;

            if (bit0 >= 65) length += (bit0 - 55) * 16 * 16 * 16;
            else length += (bit0 - 48) * 16 * 16 * 16;

            if (bit1 >= 65) length += (bit1 - 55) * 16 * 16;
            else length += (bit1 - 48) * 16 * 16;

            if (bit2 >= 65) length += (bit2 - 55) * 16;
            else length += (bit2 - 48) * 16;

            if (bit3 >= 65) length += (bit3 - 55) * 1;
            else length += (bit3 - 48) * 1;

            return length;
        }

        static public int DataStr_to_int(string DataStr)
        {
            int high_po = Convert.ToChar(DataStr.Substring(0, 1));
            int low_pol = Convert.ToChar(DataStr.Substring(1, 1));
            int length = 0;

            if (high_po >= 65) length += (high_po - 55) * 16;
            else length += (high_po - 48) * 16;

            if (low_pol >= 65) length += (low_pol - 55);
            else length += (low_pol - 48);

            return length;
        }


        static public string GetValue(string line, int[] index_save, int length)
        {
            string value = "";
            string timeset = "";
            StringBuilder value1 = new StringBuilder();

            line = line.Substring(0, line.LastIndexOf(";") + 1);
            line = Regex.Replace(line, @"\s", "");
            timeset = line.Substring(line.LastIndexOf("*"), (line.LastIndexOf(";") + 1 - line.LastIndexOf("*")));


            for (int cyc = 0; cyc < length; cyc++)
            {
                //value += line[index_save[cyc]];
                value1.Append(line[index_save[cyc]]);
            }
            value = value1.ToString();

            value = " *" + value + timeset + "//r" + (cyc_count++).ToString();
            return value;
        }


    }
}

